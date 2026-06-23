"""
LLM eval suite — 5 transformation scenarios.
Requires a real GEMINI_API_KEY. Run manually: python -m tests.evals.eval_suite
Results are printed; no assertions (LLM outputs are non-deterministic).
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.sandbox import execute_script
from app.routes import _call_llm, _TRANSFORM_PROMPT
from app.format_detect import parse_to_dataframe, build_llm_sample, dataframe_to_csv_bytes
import pandas as pd
import io

FIXTURES = Path(__file__).parent / "fixtures"

SCENARIOS = [
    {
        "id": "01",
        "name": "Standardize dates to ISO 8601",
        "file": "01_standardize_dates.csv",
        "instructions": "Standardize all date columns to ISO 8601 format (YYYY-MM-DD).",
        "check": lambda df: df["signup_date"].str.match(r"\d{4}-\d{2}-\d{2}").all(),
    },
    {
        "id": "02",
        "name": "Remove rows with >50% nulls",
        "file": "02_remove_nulls.csv",
        "instructions": "Remove rows where more than 50% of columns are empty.",
        "check": lambda df: len(df) == 2,  # Alice and Carol have only one null each
    },
    {
        "id": "03",
        "name": "Deduplicate on email, keep latest",
        "file": "03_deduplicate.csv",
        "instructions": "Remove duplicate rows keeping the most recent updated_at per email.",
        "check": lambda df: len(df) == 2 and df[df["email"] == "alice@x.com"]["name"].iloc[0] == "Alice Updated",
    },
    {
        "id": "04",
        "name": "Rename columns to snake_case",
        "file": "04_rename_columns.csv",
        "instructions": "Rename all columns to snake_case (lowercase, spaces replaced with underscores).",
        "check": lambda df: "first_name" in df.columns and "email_address" in df.columns,
    },
    {
        "id": "05",
        "name": "Filter rows by condition",
        "file": "02_remove_nulls.csv",
        "instructions": "Keep only rows where email is not empty.",
        "check": lambda df: len(df) == 2 and df["email"].notna().all(),
    },
]


async def run_scenario(scenario: dict) -> dict:
    csv_bytes = (FIXTURES / scenario["file"]).read_bytes()
    df = parse_to_dataframe(csv_bytes, "csv")
    sample, _ = build_llm_sample(df)
    prompt = _TRANSFORM_PROMPT.format(sample=sample, instructions=scenario["instructions"])

    code = await _call_llm(prompt)
    output = await execute_script(code, dataframe_to_csv_bytes(df))
    out_df = pd.read_csv(io.BytesIO(output))

    try:
        passed = scenario["check"](out_df)
    except Exception as exc:
        passed = False
        print(f"  Check error: {exc}")

    return {"id": scenario["id"], "name": scenario["name"], "passed": passed, "rows": len(out_df)}


async def main():
    results = []
    for s in SCENARIOS:
        print(f"Running {s['id']}: {s['name']} ...", end=" ", flush=True)
        try:
            r = await run_scenario(s)
            status = "PASS" if r["passed"] else "FAIL"
            print(f"{status} ({r['rows']} rows out)")
        except Exception as exc:
            print(f"ERROR: {exc}")
            r = {"id": s["id"], "name": s["name"], "passed": False}
        results.append(r)

    passed = sum(1 for r in results if r.get("passed"))
    print(f"\n{passed}/{len(results)} scenarios passed")


if __name__ == "__main__":
    asyncio.run(main())
