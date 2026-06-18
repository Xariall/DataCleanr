import io
from pathlib import Path

import pandas as pd

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


def detect_format(filename: str, content_type: str | None = None) -> str:
    """Return 'csv', 'json', or 'xlsx' based on filename extension."""
    ext = Path(filename).suffix.lower()
    if ext in {".xlsx", ".xls"}:
        return "xlsx"
    if ext == ".json":
        return "json"
    if ext == ".csv":
        return "csv"
    # Fall back to content-type sniffing
    if content_type:
        ct = content_type.lower()
        if "json" in ct:
            return "json"
        if "spreadsheet" in ct or "excel" in ct or "openxml" in ct:
            return "xlsx"
    return "csv"


def parse_to_dataframe(data: bytes, fmt: str) -> pd.DataFrame:
    """Parse raw bytes into a DataFrame. Raises ValueError on failure."""
    buf = io.BytesIO(data)
    try:
        if fmt == "csv":
            return pd.read_csv(buf)
        if fmt == "json":
            return pd.read_json(buf)
        if fmt == "xlsx":
            # First sheet only; formulas treated as NaN by openpyxl
            return pd.read_excel(buf, sheet_name=0, engine="openpyxl")
        raise ValueError(f"Unsupported format: {fmt!r}")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Failed to parse {fmt}: {exc}") from exc


def dataframe_to_csv_bytes(df: pd.DataFrame) -> bytes:
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8")


def build_llm_sample(df: pd.DataFrame, n: int = 10) -> tuple[str, int]:
    """Return (csv_sample_string, total_row_count) for use in the LLM prompt."""
    sample_csv = df.head(n).to_csv(index=False)
    return sample_csv, len(df)
