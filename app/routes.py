import json
import logging
import os

logger = logging.getLogger(__name__)

from google import genai
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .database import create_user
from .format_detect import (
    MAX_FILE_SIZE,
    build_llm_sample,
    dataframe_to_csv_bytes,
    detect_format,
    parse_to_dataframe,
)
from .middleware import check_row_budget, commit_row_usage
from .sandbox import execute_script

router = APIRouter()

_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


def _get_client() -> genai.Client:
    return genai.Client(api_key=os.environ["GEMINI_API_KEY"])

MAX_INSTRUCTIONS = 2000
PREVIEW_ROWS = 10
ROW_DROP_WARNING = 0.30  # warn if >30% rows removed

_TRANSFORM_PROMPT = """\
You are a pandas data transformation expert. You receive a CSV sample and instructions.
Write a Python script that transforms the pandas DataFrame named `df`.

Rules:
- `df` is already loaded as a pandas DataFrame. Modify or reassign it.
- Do NOT import anything. `pd` (pandas) and `np` (numpy) are already available.
- Do NOT use eval(), exec(), pd.eval(), .query(), pd.read_*(), or any file I/O.
- If you cannot interpret the instructions, output ONLY: # DataCleanr-noop: true

CSV header + first 10 rows:
{sample}

Instructions: {instructions}

Return ONLY the Python code, no explanations, no markdown fences:"""

_EXPLAIN_PROMPT = """\
You are a data transformation expert. Given plain-English data cleaning instructions,
explain what the transformation WILL do and what it will NOT do.

Instructions: {instructions}

Respond with valid JSON only, no markdown:
{{"will": "...", "will_not": "..."}}
Keep each field to 1-2 sentences. Be specific about column names if mentioned."""


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
async def _call_llm(prompt: str, max_tokens: int = 2048) -> str:
    response = await _get_client().aio.models.generate_content(
        model=_GEMINI_MODEL,
        contents=prompt,
        config={"max_output_tokens": max_tokens},
    )
    return _strip_code_fences(response.text.strip())


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences LLMs sometimes add despite instructions."""
    import re
    return re.sub(r"^```(?:python)?\n?|```$", "", text, flags=re.MULTILINE).strip()


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.post("/register")
async def register(request: Request):
    body = await request.json()
    email = str(body.get("email", "")).strip().lower()
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "Valid email required",
                "code": "INVALID_EMAIL",
                "try": 'curl -X POST /register -H \'Content-Type: application/json\' -d \'{"email":"you@example.com"}\'',
            },
        )
    try:
        api_key = create_user(email)
    except ValueError:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "Email already registered",
                "code": "EMAIL_EXISTS",
                "try": "Use your existing API key, or contact support.",
            },
        )
    return {
        "api_key": api_key,
        "message": "Store this key safely — it will not be shown again.",
    }


@router.post("/explain")
async def explain(request: Request, instructions: str = Form(...)):
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail={"error": "Unauthorized", "code": "MISSING_API_KEY"})

    instructions = instructions.strip()
    if not instructions:
        raise HTTPException(
            status_code=400,
            detail={"error": "instructions cannot be empty", "code": "EMPTY_INSTRUCTIONS"},
        )
    if len(instructions) > MAX_INSTRUCTIONS:
        raise HTTPException(
            status_code=400,
            detail={"error": f"instructions exceeds {MAX_INSTRUCTIONS} characters", "code": "INSTRUCTIONS_TOO_LONG"},
        )

    # /explain counts as 1 row against the quota to prevent abuse
    try:
        allowed, used, limit = await check_row_budget(user, 1)
    except RuntimeError:
        raise HTTPException(
            status_code=503,
            detail={"error": "Rate-limit service unavailable", "code": "SERVICE_UNAVAILABLE"},
        )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "Daily row budget exceeded",
                "code": "RATE_LIMIT_EXCEEDED",
                "retry_after": 3600,
                "try": "Upgrade to paid at /upgrade for 500K rows/day",
            },
        )

    try:
        raw = await _call_llm(_EXPLAIN_PROMPT.format(instructions=instructions), max_tokens=512)
    except Exception:
        raise HTTPException(status_code=502, detail={"error": "LLM unavailable", "code": "LLM_UNAVAILABLE"})

    try:
        parsed = json.loads(raw)
        will = str(parsed.get("will", ""))
        will_not = str(parsed.get("will_not", ""))
    except (json.JSONDecodeError, KeyError):
        will = raw
        will_not = ""

    await commit_row_usage(user, 1)
    return {"will": will, "will_not": will_not}


async def _run_transform(
    request: Request,
    file: UploadFile,
    instructions: str,
    preview: bool = False,
) -> Response:
    """Shared logic for /transform and /preview."""
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail={"error": "Unauthorized", "code": "MISSING_API_KEY"})

    instructions = instructions.strip()
    if not instructions:
        raise HTTPException(
            status_code=400,
            detail={"error": "instructions cannot be empty", "code": "EMPTY_INSTRUCTIONS",
                    "try": 'curl ... -F "instructions=remove rows where email is empty"'},
        )
    if len(instructions) > MAX_INSTRUCTIONS:
        raise HTTPException(
            status_code=400,
            detail={"error": f"instructions exceeds {MAX_INSTRUCTIONS} characters", "code": "INSTRUCTIONS_TOO_LONG"},
        )

    # Read and size-gate the file
    raw = await file.read()
    if len(raw) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail={
                "error": "File exceeds 10 MB limit",
                "code": "FILE_TOO_LARGE",
                "try": "Split the file into chunks under 10 MB",
            },
        )

    fmt = detect_format(file.filename or "", file.content_type)
    try:
        df = parse_to_dataframe(raw, fmt)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": str(exc), "code": "INVALID_FILE"},
        )

    row_count = len(df)
    if row_count == 0:
        raise HTTPException(
            status_code=400,
            detail={"error": "Uploaded file has no data rows", "code": "EMPTY_FILE"},
        )

    # Rate-limit check (preview skips deduction but still validates key)
    if not preview:
        try:
            allowed, used, limit = await check_row_budget(user, row_count)
        except RuntimeError:
            raise HTTPException(
                status_code=503,
                detail={"error": "Rate-limit service unavailable", "code": "SERVICE_UNAVAILABLE"},
            )
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail={
                    "error": f"Daily row budget exceeded ({used}/{limit})",
                    "code": "RATE_LIMIT_EXCEEDED",
                    "retry_after": 3600,
                    "try": "Upgrade to paid at /upgrade for 500K rows/day",
                },
            )

    # Build LLM prompt from header + first 10 rows
    sample_csv, _ = build_llm_sample(df, n=10)
    prompt = _TRANSFORM_PROMPT.format(sample=sample_csv, instructions=instructions)

    try:
        code = await _call_llm(prompt)
        logger.info("Generated code: %r", code[:200])
    except Exception as exc:
        logger.error("LLM call failed: %s: %s", type(exc).__name__, exc)
        raise HTTPException(status_code=502, detail={"error": "LLM unavailable", "code": "LLM_UNAVAILABLE"})

    # For preview: slice to first PREVIEW_ROWS before execution
    if preview:
        preview_df = df.head(PREVIEW_ROWS)
        input_csv = dataframe_to_csv_bytes(preview_df)
        exec_timeout = 3.0
    else:
        input_csv = dataframe_to_csv_bytes(df)
        exec_timeout = 30.0

    try:
        output_csv = await execute_script(code, input_csv, timeout=exec_timeout)
    except ValueError as exc:
        code_str = str(exc)
        if "BLOCKED_INSTRUCTIONS" in code_str:
            raise HTTPException(
                status_code=400,
                detail={"error": "Instructions reference blocked operations", "code": "BLOCKED_INSTRUCTIONS",
                        "try": "Rephrase to avoid eval/exec/file operations"},
            )
        raise HTTPException(
            status_code=400,
            detail={"error": "Could not interpret instructions", "code": "UNINTERPRETABLE_INSTRUCTIONS",
                    "try": "Be more specific: 'remove rows where email is empty'"},
        )
    except RuntimeError as exc:
        msg = str(exc)
        logger.error("Sandbox error: %s", msg)
        if "TRANSFORM_TIMEOUT" in msg:
            raise HTTPException(status_code=502, detail={"error": "Transform timed out", "code": "TRANSFORM_TIMEOUT"})
        raise HTTPException(status_code=502, detail={"error": "Transform failed", "code": "TRANSFORM_FAILED"})

    # Validate output
    import io
    import pandas as pd
    try:
        out_df = pd.read_csv(io.BytesIO(output_csv))
    except Exception:
        raise HTTPException(status_code=502, detail={"error": "Transform produced invalid CSV", "code": "TRANSFORM_FAILED"})

    out_rows = len(out_df)
    if out_rows == 0:
        raise HTTPException(
            status_code=400,
            detail={"error": "Transform removed all rows", "code": "EMPTY_RESULT",
                    "try": "Check your instructions — they may be too aggressive"},
        )

    # Build summary
    input_rows = len(df) if not preview else PREVIEW_ROWS
    rows_removed = max(0, input_rows - out_rows)
    cols_normalized = [c for c in out_df.columns if c != c.strip() or c != c.lower()]

    summary = {
        "rows_in": input_rows,
        "rows_out": out_rows,
        "rows_removed": rows_removed,
        "format_detected": fmt,
        "preview": preview,
    }

    headers: dict[str, str] = {
        "X-DataCleanr-Summary": (
            f"Removed {rows_removed} rows, {input_rows - out_rows} rows remaining"
        ),
        "X-DataCleanr-Stats": str(summary),
    }

    # Warn if >30% rows removed
    if not preview and input_rows > 0 and (rows_removed / input_rows) > ROW_DROP_WARNING:
        headers["X-DataCleanr-Warning"] = (
            f"Removed {rows_removed / input_rows:.0%} of input rows - verify instructions"
        )

    # Commit usage after success (not on preview)
    if not preview:
        await commit_row_usage(user, row_count)

    return Response(
        content=output_csv,
        media_type="text/csv",
        headers=headers,
    )


@router.post("/transform")
async def transform(
    request: Request,
    file: UploadFile = File(...),
    instructions: str = Form(...),
):
    return await _run_transform(request, file, instructions, preview=False)


@router.post("/preview")
async def preview(
    request: Request,
    file: UploadFile = File(...),
    instructions: str = Form(...),
):
    """Same as /transform but first 10 rows only, no quota deduction."""
    return await _run_transform(request, file, instructions, preview=True)
