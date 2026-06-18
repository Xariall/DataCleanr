import pytest
from app.sandbox import validate_script, execute_script


# --- validate_script ---

def test_clean_script_passes():
    code = "df = df.dropna()"
    result = validate_script(code)
    assert result.safe is True
    assert result.reason == "ok"


def test_noop_marker_detected():
    code = "# DataCleanr-noop: true\ndf = df"
    result = validate_script(code)
    assert result.safe is True
    assert result.reason == "noop"


@pytest.mark.parametrize("bad_code", [
    "import os",
    "import subprocess",
    "import pickle",
    "from os import getcwd",
    "from subprocess import run",
    "import requests",
    "import socket",
    "import ctypes",
    "import sys",
    "eval('1+1')",
    "exec('x=1')",
    "__import__('os')",
    "pd.eval('df')",
    "df.query('a > 1')",
    "pd.read_csv('file.csv')",
    "x = getattr(df, 'values')",
])
def test_blocked_patterns(bad_code):
    result = validate_script(bad_code)
    assert result.safe is False, f"Expected {bad_code!r} to be blocked"


def test_syntax_error_blocked():
    result = validate_script("def f(:\n  pass")
    assert result.safe is False
    assert "SyntaxError" in result.reason


# --- execute_script ---

@pytest.mark.asyncio
async def test_execute_simple_transform():
    csv = b"name,age\nAlice,30\nBob,\n"
    code = "df = df.dropna()"
    output = await execute_script(code, csv)
    assert b"Alice" in output
    assert b"Bob" not in output


@pytest.mark.asyncio
async def test_execute_blocked_raises_value_error():
    csv = b"a,b\n1,2\n"
    with pytest.raises(ValueError, match="BLOCKED_INSTRUCTIONS"):
        await execute_script("import os", csv)


@pytest.mark.asyncio
async def test_execute_noop_raises_value_error():
    csv = b"a,b\n1,2\n"
    with pytest.raises(ValueError, match="UNINTERPRETABLE_INSTRUCTIONS"):
        await execute_script("# DataCleanr-noop: true", csv)


@pytest.mark.asyncio
async def test_execute_timeout():
    csv = b"a,b\n1,2\n"
    code = "import time; time.sleep(99)"
    with pytest.raises((RuntimeError, ValueError)):
        await execute_script(code, csv, timeout=0.5)
