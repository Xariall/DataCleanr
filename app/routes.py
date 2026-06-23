import json
import logging
import os
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _seconds_until_midnight() -> int:
    now = datetime.now(timezone.utc)
    midnight = now.replace(hour=23, minute=59, second=59, microsecond=0)
    return max(0, int((midnight - now).total_seconds()))

from google import genai
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .database import create_user, get_stats, log_transform, rotate_api_key
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

_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")

_LANDING_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DataCleanr — Clean CSV with plain English</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --bg: #0d0d0f;
    --surface: #16161a;
    --border: #2a2a30;
    --text: #e8e8ed;
    --muted: #888892;
    --accent: #6ee7b7;
    --accent-dim: #1a3d31;
    --code-bg: #111115;
    --yellow: #fbbf24;
    --red: #f87171;
    --r: 8px;
  }
  body { background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; line-height: 1.6; }
  a { color: var(--accent); text-decoration: none; }
  a:hover { text-decoration: underline; }

  /* NAV */
  nav { display: flex; justify-content: space-between; align-items: center; padding: 1.25rem 2rem; border-bottom: 1px solid var(--border); }
  .logo { font-weight: 700; font-size: 1.1rem; letter-spacing: -0.02em; color: var(--text); }
  .logo span { color: var(--accent); }
  .nav-links { display: flex; gap: 1.5rem; font-size: 0.9rem; color: var(--muted); }
  .nav-links a { color: var(--muted); }
  .nav-cta { background: var(--accent); color: #0d0d0f; font-weight: 600; padding: 0.45rem 1rem; border-radius: var(--r); font-size: 0.875rem; }
  .nav-cta:hover { text-decoration: none; opacity: 0.9; }

  /* HERO */
  .hero { max-width: 900px; margin: 0 auto; padding: 5rem 2rem 3rem; text-align: center; }
  .badge { display: inline-flex; align-items: center; gap: 0.4rem; background: var(--accent-dim); color: var(--accent); font-size: 0.78rem; font-weight: 600; padding: 0.3rem 0.75rem; border-radius: 999px; border: 1px solid var(--accent); margin-bottom: 1.75rem; letter-spacing: 0.04em; text-transform: uppercase; }
  h1 { font-size: clamp(2rem, 5vw, 3.5rem); font-weight: 800; letter-spacing: -0.03em; line-height: 1.1; margin-bottom: 1.25rem; }
  h1 em { color: var(--accent); font-style: normal; }
  .subtitle { font-size: clamp(1rem, 2vw, 1.2rem); color: var(--muted); max-width: 600px; margin: 0 auto 2.5rem; }
  .cta-row { display: flex; justify-content: center; gap: 1rem; flex-wrap: wrap; margin-bottom: 3.5rem; }
  .btn-primary { background: var(--accent); color: #0d0d0f; font-weight: 700; padding: 0.75rem 1.75rem; border-radius: var(--r); font-size: 1rem; }
  .btn-primary:hover { text-decoration: none; opacity: 0.9; }
  .btn-secondary { border: 1px solid var(--border); color: var(--muted); padding: 0.75rem 1.75rem; border-radius: var(--r); font-size: 1rem; }
  .btn-secondary:hover { text-decoration: none; border-color: var(--muted); color: var(--text); }

  /* CODE BLOCK */
  .code-block { background: var(--code-bg); border: 1px solid var(--border); border-radius: var(--r); text-align: left; overflow: auto; max-width: 720px; margin: 0 auto; }
  .code-block-header { display: flex; justify-content: space-between; align-items: center; padding: 0.6rem 1rem; border-bottom: 1px solid var(--border); font-size: 0.78rem; color: var(--muted); }
  .dots { display: flex; gap: 6px; }
  .dot { width: 10px; height: 10px; border-radius: 50%; }
  .dot.r { background: #f87171; } .dot.y { background: #fbbf24; } .dot.g { background: var(--accent); }
  pre { padding: 1.25rem 1.5rem; font-size: 0.85rem; font-family: "SF Mono", "Fira Code", monospace; line-height: 1.7; overflow-x: auto; }
  .c-muted { color: var(--muted); } .c-acc { color: var(--accent); } .c-str { color: #93c5fd; } .c-kw { color: var(--yellow); }

  /* DIVIDER */
  .section { max-width: 900px; margin: 0 auto; padding: 4rem 2rem; }
  .section-title { font-size: 1.5rem; font-weight: 700; margin-bottom: 2rem; letter-spacing: -0.02em; text-align: center; }

  /* FEATURES */
  .features { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 1rem; }
  .feature { background: var(--surface); border: 1px solid var(--border); border-radius: var(--r); padding: 1.5rem; }
  .feature-icon { font-size: 1.5rem; margin-bottom: 0.75rem; }
  .feature h3 { font-size: 1rem; font-weight: 600; margin-bottom: 0.4rem; }
  .feature p { font-size: 0.875rem; color: var(--muted); }

  /* HOW IT WORKS */
  .steps { display: flex; flex-direction: column; gap: 1.25rem; }
  .step { display: flex; gap: 1.25rem; align-items: flex-start; }
  .step-num { flex-shrink: 0; width: 2rem; height: 2rem; border-radius: 50%; background: var(--accent-dim); border: 1px solid var(--accent); display: flex; align-items: center; justify-content: center; font-size: 0.8rem; font-weight: 700; color: var(--accent); }
  .step-body h3 { font-size: 1rem; font-weight: 600; margin-bottom: 0.2rem; }
  .step-body p { font-size: 0.875rem; color: var(--muted); }
  code { background: var(--code-bg); border: 1px solid var(--border); padding: 0.1em 0.4em; border-radius: 4px; font-size: 0.85em; font-family: "SF Mono", "Fira Code", monospace; color: var(--accent); }

  /* PRICING */
  .pricing { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 1.5rem; }
  .plan { background: var(--surface); border: 1px solid var(--border); border-radius: var(--r); padding: 2rem; }
  .plan.featured { border-color: var(--accent); position: relative; }
  .plan-tag { position: absolute; top: -1px; right: 1.5rem; background: var(--accent); color: #0d0d0f; font-size: 0.72rem; font-weight: 700; padding: 0.2rem 0.6rem; border-radius: 0 0 6px 6px; text-transform: uppercase; letter-spacing: 0.05em; }
  .plan-name { font-size: 0.85rem; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: 0.07em; margin-bottom: 0.5rem; }
  .plan-price { font-size: 2.5rem; font-weight: 800; letter-spacing: -0.04em; margin-bottom: 0.25rem; }
  .plan-price span { font-size: 1rem; font-weight: 400; color: var(--muted); }
  .plan-desc { font-size: 0.875rem; color: var(--muted); margin-bottom: 1.5rem; }
  .plan-features { list-style: none; display: flex; flex-direction: column; gap: 0.6rem; margin-bottom: 1.75rem; }
  .plan-features li { font-size: 0.875rem; display: flex; gap: 0.5rem; }
  .plan-features li::before { content: "\\2713"; color: var(--accent); font-weight: 700; }
  .plan-btn { display: block; text-align: center; padding: 0.65rem 1rem; border-radius: var(--r); font-weight: 600; font-size: 0.9rem; border: 1px solid var(--border); color: var(--muted); }
  .plan.featured .plan-btn { background: var(--accent); color: #0d0d0f; border: none; }
  .plan-btn:hover { text-decoration: none; opacity: 0.85; }

  /* FOOTER */
  footer { border-top: 1px solid var(--border); text-align: center; padding: 2rem; font-size: 0.85rem; color: var(--muted); }
  footer a { color: var(--muted); margin: 0 0.5rem; }
</style>
</head>
<body>

<nav>
  <span class="logo">Data<span>Cleanr</span></span>
  <div class="nav-links">
    <a href="/docs">API Docs</a>
    <a href="#pricing">Pricing</a>
  </div>
  <a class="nav-cta" href="#register-box" onclick="document.getElementById('reg-email').focus()">Get API Key &rarr;</a>
</nav>

<div class="hero">
  <div class="badge">&#x2714; REST API &bull; Works from any language</div>
  <h1>Clean CSV files with<br><em>plain English</em></h1>
  <p class="subtitle">POST a messy CSV/JSON/xlsx + your instructions &rarr; get clean CSV back. No Python required.</p>

  <div id="register-box" style="max-width:480px;margin:0 auto 2.5rem;">
    <div style="display:flex;gap:0.5rem;">
      <input id="reg-email" type="email" placeholder="you@example.com"
        style="flex:1;background:var(--surface);border:1px solid var(--border);border-radius:var(--r);
               padding:0.75rem 1rem;color:var(--text);font-size:1rem;outline:none;"
        onkeydown="if(event.key==='Enter')doRegister()" />
      <button onclick="doRegister()"
        style="background:var(--accent);color:#0d0d0f;font-weight:700;padding:0.75rem 1.25rem;
               border:none;border-radius:var(--r);font-size:1rem;cursor:pointer;white-space:nowrap;">
        Get free API key &rarr;
      </button>
    </div>
    <div id="reg-msg" style="margin-top:0.75rem;font-size:0.875rem;"></div>
  </div>

  <div id="key-box" style="display:none;max-width:720px;margin:0 auto 2.5rem;">
    <div class="code-block">
      <div class="code-block-header">
        <div class="dots"><div class="dot r"></div><div class="dot y"></div><div class="dot g"></div></div>
        <span>Your API key is ready</span>
        <button onclick="copyKey()" id="copy-btn"
          style="background:none;border:1px solid var(--border);color:var(--muted);
                 padding:0.2rem 0.6rem;border-radius:4px;cursor:pointer;font-size:0.75rem;">copy</button>
      </div>
      <pre id="key-display" style="color:var(--accent);font-size:1rem;letter-spacing:0.02em;"></pre>
    </div>
    <div class="code-block" style="margin-top:1rem;">
      <div class="code-block-header">
        <div class="dots"><div class="dot r"></div><div class="dot y"></div><div class="dot g"></div></div>
        <span>Next step — clean your first file</span>
        <span></span>
      </div>
      <pre id="curl-display" style="font-size:0.82rem;"></pre>
    </div>
  </div>

  <div id="initial-code" class="code-block" style="max-width:720px;margin:0 auto 2.5rem;">
    <div class="code-block-header">
      <div class="dots"><div class="dot r"></div><div class="dot y"></div><div class="dot g"></div></div>
      <span>terminal</span><span></span>
    </div>
    <pre><span class="c-muted"># 1. Register above — get your key instantly</span>

<span class="c-muted"># 2. Clean your data</span>
<span class="c-kw">curl</span> -X POST https://datacleanr-production.up.railway.app/transform \\
  -H <span class="c-str">"X-API-Key: dc_..."</span> \\
  -F <span class="c-str">"file=@customers.csv"</span> \\
  -F <span class="c-str">"instructions=remove rows where email is empty, standardize dates to ISO 8601"</span> \\
  -o <span class="c-acc">clean.csv</span></pre>
  </div>

  <div style="margin-bottom:2rem;">
    <a class="btn-secondary" href="#how-it-works">See how it works</a>
  </div>

<script>
async function doRegister() {
  const email = document.getElementById('reg-email').value.trim();
  const msg = document.getElementById('reg-msg');
  if (!email || !email.includes('@')) {
    msg.style.color = 'var(--red)';
    msg.textContent = 'Enter a valid email address.';
    return;
  }
  msg.style.color = 'var(--muted)';
  msg.textContent = 'Registering...';
  try {
    const r = await fetch('/register', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({email})
    });
    const data = await r.json();
    if (!r.ok) {
      const code = data?.detail?.code || 'ERROR';
      msg.style.color = 'var(--red)';
      msg.textContent = code === 'EMAIL_EXISTS'
        ? 'This email is already registered. Check your original API key.'
        : (data?.detail?.error || 'Something went wrong.');
      return;
    }
    const key = data.api_key;
    document.getElementById('key-display').textContent = key;
    document.getElementById('curl-display').innerHTML =
      '<span style="color:var(--muted)"># Save this key — it won\\'t be shown again</span>\\n' +
      '<span style="color:var(--yellow)">curl</span> -X POST https://datacleanr-production.up.railway.app/transform \\\\\\n' +
      '  -H <span style="color:#93c5fd">"X-API-Key: ' + key + '"</span> \\\\\\n' +
      '  -F <span style="color:#93c5fd">"file=@data.csv"</span> \\\\\\n' +
      '  -F <span style="color:#93c5fd">"instructions=remove rows where email is empty"</span> \\\\\\n' +
      '  -o <span style="color:var(--accent)">clean.csv</span>';
    document.getElementById('register-box').style.display = 'none';
    document.getElementById('initial-code').style.display = 'none';
    document.getElementById('key-box').style.display = 'block';
  } catch(e) {
    msg.style.color = 'var(--red)';
    msg.textContent = 'Network error. Try again.';
  }
}
function copyKey() {
  const key = document.getElementById('key-display').textContent;
  navigator.clipboard.writeText(key).then(() => {
    const btn = document.getElementById('copy-btn');
    btn.textContent = 'copied!';
    btn.style.color = 'var(--accent)';
    setTimeout(() => { btn.textContent = 'copy'; btn.style.color = ''; }, 2000);
  });
}
</script>
</div>

<div class="section" id="how-it-works">
  <div class="section-title">How it works</div>
  <div class="steps">
    <div class="step">
      <div class="step-num">1</div>
      <div class="step-body">
        <h3>Upload your file</h3>
        <p>Send any CSV, JSON, or xlsx file up to 10 MB. We auto-detect the format.</p>
      </div>
    </div>
    <div class="step">
      <div class="step-num">2</div>
      <div class="step-body">
        <h3>Describe what you want</h3>
        <p>Write instructions in plain English: <code>remove duplicates</code>, <code>standardize phone numbers</code>, <code>fill blanks with N/A</code> &mdash; anything.</p>
      </div>
    </div>
    <div class="step">
      <div class="step-num">3</div>
      <div class="step-body">
        <h3>AI generates &amp; executes a pandas script</h3>
        <p>Gemini 2.5-flash writes the code. An AST-sandboxed subprocess runs it safely. No network access, no file I/O.</p>
      </div>
    </div>
    <div class="step">
      <div class="step-num">4</div>
      <div class="step-body">
        <h3>Get clean CSV back</h3>
        <p>Response includes <code>X-DataCleanr-Summary</code> and <code>X-DataCleanr-Warning</code> headers with stats.</p>
      </div>
    </div>
  </div>
</div>

<div class="section">
  <div class="section-title">Built for developers</div>
  <div class="features">
    <div class="feature">
      <div class="feature-icon">&#x1F5C2;</div>
      <h3>Any input format</h3>
      <p>CSV, JSON, and xlsx all work. Auto-detected from file extension and content type.</p>
    </div>
    <div class="feature">
      <div class="feature-icon">&#x1F512;</div>
      <h3>Sandboxed execution</h3>
      <p>Generated code runs in an AST-restricted subprocess. No <code>eval</code>, no network, no disk I/O.</p>
    </div>
    <div class="feature">
      <div class="feature-icon">&#x26A1;</div>
      <h3>Any language, any stack</h3>
      <p>Just HTTP. Works from Go, Node, Ruby, PHP, shell scripts, n8n, Zapier &mdash; anywhere that speaks curl.</p>
    </div>
    <div class="feature">
      <div class="feature-icon">&#x1F4CA;</div>
      <h3>Preview before committing</h3>
      <p>POST to <code>/preview</code> to dry-run on the first 10 rows without spending your quota.</p>
    </div>
    <div class="feature">
      <div class="feature-icon">&#x1F4AC;</div>
      <h3>Explain before running</h3>
      <p>POST to <code>/explain</code> to get a plain-English breakdown of what your instructions will and won&rsquo;t do.</p>
    </div>
    <div class="feature">
      <div class="feature-icon">&#x1F504;</div>
      <h3>Key rotation</h3>
      <p>POST to <code>/rotate-key</code> to invalidate your old API key and get a new one instantly.</p>
    </div>
  </div>
</div>

<div class="section" id="pricing">
  <div class="section-title">Free to get started</div>
  <div class="pricing" style="max-width:420px;margin:0 auto;">
    <div class="plan featured">
      <div class="plan-name">Free</div>
      <div class="plan-price">$0 <span>/ month</span></div>
      <div class="plan-desc">No credit card. Get started in 30 seconds.</div>
      <ul class="plan-features">
        <li>500 rows / day</li>
        <li>CSV, JSON, xlsx input</li>
        <li>/preview — dry-run first 10 rows</li>
        <li>/me — check your daily usage</li>
        <li>Full API access at /docs</li>
      </ul>
      <a class="plan-btn" href="/docs">Get free API key &rarr;</a>
    </div>
  </div>
  <p style="text-align:center;margin-top:1.5rem;font-size:0.875rem;color:var(--muted);">Need higher limits? <a href="mailto:supersanin45@gmail.com">Contact us</a></p>
</div>

<footer>
  <div>
    <a href="/docs">API Docs</a>
    <a href="/redoc">ReDoc</a>
    <a href="https://github.com/Xariall/DataCleanr" target="_blank">GitHub</a>
  </div>
  <div style="margin-top:0.75rem">DataCleanr &mdash; clean data, plain English.</div>
</footer>

</body>
</html>"""


def _get_client() -> genai.Client:
    return genai.Client(api_key=os.environ["GEMINI_API_KEY"])

MAX_INSTRUCTIONS = 2000
PREVIEW_ROWS = 10
ROW_DROP_WARNING = 0.30  # warn if >30% rows removed

_TRANSFORM_PROMPT = """\
You are a pandas data transformation expert. You receive a CSV sample and instructions.
Write a Python script that transforms the pandas DataFrame named `df`.

Strict rules — violations will cause an error:
- `df` is already loaded as a pandas DataFrame. Only modify or reassign `df`.
- Do NOT add any import statements. `pd` and `np` are already available.
- NEVER use: eval(), exec(), compile(), open(), getattr(), setattr(), __import__()
- NEVER use: pd.eval(), df.query(), pd.read_csv(), pd.read_excel(), pd.read_json()
- NEVER reference: __class__, __bases__, __subclasses__, builtins
- Use boolean indexing instead of .query(): write `df[df['col'] > 0]` not `df.query('col > 0')`
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
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=2, max=15),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
async def _call_llm(prompt: str, max_tokens: int = 2048) -> str:
    response = await _get_client().aio.models.generate_content(
        model=_GEMINI_MODEL,
        contents=prompt,
        config={"max_output_tokens": max_tokens},
    )
    return _normalize_code(_strip_code_fences(response.text.strip()))


def _strip_code_fences(text: str) -> str:
    """Remove only the outermost markdown code fence, not backticks inside the code."""
    import re
    text = re.sub(r"^\s*```(?:python|py)?\s*\n?", "", text)
    text = re.sub(r"\n?\s*```\s*$", "", text)
    return text.strip()


def _normalize_code(code: str) -> str:
    """Normalize LLM-generated code: fix line endings, strip BOM and zero-width chars."""
    # Strip BOM and zero-width characters that cause tokenizer errors
    code = code.lstrip("﻿​‌‍￾")
    # Normalize Windows/Mac line endings to Unix
    code = code.replace("\r\n", "\n").replace("\r", "\n")
    # Remove null bytes
    code = code.replace("\x00", "")
    return code


def _extract_stderr_hint(runtime_msg: str) -> str:
    """Pull the most useful line from a TRANSFORM_FAILED message for user display."""
    prefix = "TRANSFORM_FAILED: "
    stderr = runtime_msg[len(prefix):] if runtime_msg.startswith(prefix) else runtime_msg
    for line in reversed(stderr.splitlines()):
        line = line.strip()
        if line and any(kw in line for kw in ("Error", "error", "Exception", "KeyError", "ValueError")):
            return line[:200]
    return stderr.strip()[:200] or "Unknown error"


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def landing():
    return HTMLResponse(_LANDING_HTML)


@router.get("/upgrade")
async def upgrade():
    link = os.getenv("STRIPE_PAYMENT_LINK", "")
    if not link:
        raise HTTPException(
            status_code=503,
            detail={"error": "Upgrade not available yet — check back soon", "code": "UPGRADE_UNAVAILABLE"},
        )
    return RedirectResponse(url=link, status_code=302)


@router.get("/me")
async def me(request: Request):
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail={"error": "Unauthorized", "code": "MISSING_API_KEY"})
    try:
        _, used, limit = await check_row_budget(user, 0)
    except RuntimeError:
        used, limit = 0, (int(os.getenv("FREE_DAILY_ROWS", "500")) if user["tier"] == "FREE" else int(os.getenv("PAID_DAILY_ROWS", "500000")))
    return {
        "email": user["email"],
        "tier": user["tier"],
        "rows_used_today": used,
        "rows_limit_today": limit,
        "payment_failing": bool(user["payment_failing"]),
        "upgrade_url": "/upgrade" if user["tier"] == "FREE" else None,
    }


@router.post("/rotate-key")
async def rotate_key(request: Request):
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail={"error": "Unauthorized", "code": "MISSING_API_KEY"})
    new_key = rotate_api_key(user["id"])
    return {
        "api_key": new_key,
        "message": "Old key is immediately invalidated. Store this key safely — it will not be shown again.",
    }


@router.get("/stats")
async def stats(request: Request):
    secret = os.getenv("ADMIN_SECRET", "")
    provided = request.headers.get("X-Admin-Secret", "")
    if not secret or provided != secret:
        raise HTTPException(status_code=403, detail={"error": "Forbidden", "code": "FORBIDDEN"})
    return get_stats()


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
        "next_step": (
            f'curl -X POST https://datacleanr-production.up.railway.app/transform'
            f' -H "X-API-Key: {api_key}"'
            f' -F "file=@data.csv"'
            f' -F "instructions=remove rows where email is empty"'
            f' -o clean.csv'
        ),
        "docs": "https://datacleanr-production.up.railway.app/docs",
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
    return {
        "will": will,
        "will_not": will_not,
        "tip": "Use /preview with the same instructions to dry-run on your actual data.",
    }


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

    # Rate-limit check — always fetch used/limit for response headers
    _check_count = row_count if not preview else 0
    try:
        allowed, used, limit = await check_row_budget(user, _check_count)
    except RuntimeError:
        if not preview:
            raise HTTPException(
                status_code=503,
                detail={"error": "Rate-limit service unavailable", "code": "SERVICE_UNAVAILABLE"},
            )
        from .middleware import FREE_DAILY_ROWS, PAID_DAILY_ROWS
        used, limit = 0, PAID_DAILY_ROWS if user["tier"] == "PAID" else FREE_DAILY_ROWS
        allowed = True

    if not preview and not allowed:
        raise HTTPException(
            status_code=429,
            headers={
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(_seconds_until_midnight()),
            },
            detail={
                "error": f"Daily row budget exceeded ({used}/{limit})",
                "code": "RATE_LIMIT_EXCEEDED",
                "retry_after": _seconds_until_midnight(),
            },
        )

    # Build LLM prompt from header + first 10 rows
    sample_csv, _ = build_llm_sample(df, n=10)
    prompt = _TRANSFORM_PROMPT.format(sample=sample_csv, instructions=instructions)

    t0 = time.monotonic()
    code = ""
    for _attempt in range(2):  # retry once on syntax error
        try:
            code = await _call_llm(prompt)
            llm_ms = int((time.monotonic() - t0) * 1000)
            logger.info("llm_ok user=%s rows=%d llm_ms=%d attempt=%d", user["email"], row_count, llm_ms, _attempt + 1)
            break
        except Exception as exc:
            logger.error("llm_fail user=%s attempt=%d error=%s: %s", user["email"], _attempt + 1, type(exc).__name__, exc)
            if _attempt == 1:
                raise HTTPException(status_code=502, detail={"error": "LLM unavailable", "code": "LLM_UNAVAILABLE"})

    # For preview: slice to first PREVIEW_ROWS before execution
    if preview:
        preview_df = df.head(PREVIEW_ROWS)
        input_csv = dataframe_to_csv_bytes(preview_df)
        exec_timeout = 3.0
    else:
        input_csv = dataframe_to_csv_bytes(df)
        exec_timeout = 30.0

    t1 = time.monotonic()
    try:
        output_csv = await execute_script(code, input_csv, timeout=exec_timeout)
    except ValueError as exc:
        code_str = str(exc)
        if "BLOCKED_INSTRUCTIONS" in code_str:
            reason = code_str.replace("BLOCKED_INSTRUCTIONS: ", "", 1)
            if "SyntaxError" in reason:
                # LLM produced malformed code — retry with simpler instructions
                logger.warning("syntax_error user=%s reason=%r code=%r", user["email"], reason, code[:500])
                raise HTTPException(
                    status_code=502,
                    detail={
                        "error": "LLM generated malformed code",
                        "code": "LLM_GENERATED_INVALID_CODE",
                        "try": "Try again — the model occasionally generates invalid Python. If it keeps failing, simplify your instructions.",
                    },
                )
            logger.warning("blocked user=%s reason=%r code=%r", user["email"], reason, code[:300])
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "Generated code contains a blocked operation",
                    "code": "BLOCKED_INSTRUCTIONS",
                    "reason": reason,
                    "try": "Rephrase your instructions to avoid filtering patterns like .query() or eval()",
                },
            )
        raise HTTPException(
            status_code=400,
            detail={"error": "Could not interpret instructions", "code": "UNINTERPRETABLE_INSTRUCTIONS",
                    "try": "Be more specific: 'remove rows where email is empty'"},
        )
    except RuntimeError as exc:
        msg = str(exc)
        logger.error("sandbox_fail user=%s err=%s", user["email"], msg[:300])
        if "TRANSFORM_TIMEOUT" in msg:
            raise HTTPException(status_code=502, detail={"error": "Transform timed out", "code": "TRANSFORM_TIMEOUT",
                                                         "try": "Simplify your instructions or reduce file size"})
        hint = _extract_stderr_hint(msg)
        raise HTTPException(status_code=502, detail={
            "error": "Transform failed",
            "code": "TRANSFORM_FAILED",
            "hint": hint,
            "try": "Try /preview to test on 10 rows first",
        })

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

    rows_after = used + (row_count if not preview else 0)
    headers: dict[str, str] = {
        "X-DataCleanr-Summary": (
            f"Removed {rows_removed} rows, {out_rows} rows remaining"
        ),
        "X-DataCleanr-Stats": str(summary),
        "X-RateLimit-Limit": str(limit),
        "X-RateLimit-Remaining": str(max(0, limit - rows_after)),
        "X-RateLimit-Reset": str(_seconds_until_midnight()),
    }

    # Warn if >30% rows removed
    if not preview and input_rows > 0 and (rows_removed / input_rows) > ROW_DROP_WARNING:
        headers["X-DataCleanr-Warning"] = (
            f"Removed {rows_removed / input_rows:.0%} of input rows - verify instructions"
        )

    # Commit usage after success (not on preview)
    if not preview:
        await commit_row_usage(user, row_count)

    sandbox_ms = int((time.monotonic() - t1) * 1000)
    total_ms = int((time.monotonic() - t0) * 1000)
    logger.info(
        "transform_ok user=%s rows_in=%d rows_out=%d llm_ms=%d sandbox_ms=%d total_ms=%d preview=%s fmt=%s",
        user["email"], input_rows, out_rows, llm_ms, sandbox_ms, total_ms, preview, fmt,
    )
    log_transform(user["id"], input_rows, out_rows, fmt, llm_ms, total_ms, preview)

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
