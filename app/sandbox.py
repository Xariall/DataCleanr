import ast
import asyncio
import os
import sys
import tempfile
from typing import NamedTuple

# Modules the LLM must never import inside the generated script.
_DENIED_IMPORTS: frozenset[str] = frozenset({
    "pickle", "pickletools", "shelve", "marshal",
    "ctypes", "cffi",
    "requests", "httpx", "urllib", "urllib3", "aiohttp",
    "socket", "socketserver",
    "subprocess", "os", "sys", "signal", "pathlib",
    "io", "builtins", "importlib", "imp",
    "multiprocessing", "threading", "concurrent",
    "pdb", "debugpy", "ast",
})

# Bare-name calls to block (e.g. eval(...), exec(...)).
_DENIED_CALLS: frozenset[str] = frozenset({
    "eval", "exec", "compile", "__import__", "open",
    "getattr", "setattr", "delattr",
})

# Method-attribute calls to block regardless of receiver.
_DENIED_ATTRS: frozenset[str] = frozenset({"eval", "exec", "compile"})

# Fast substring checks — catches patterns AST misses (e.g. string-based evals).
_DENIED_SUBSTRINGS: tuple[str, ...] = (
    "pd.eval(", ".query(", "pd.read_",
    "__class__", "__bases__", "__subclasses__", "mro(",
    "builtins", "__builtins__",
)

NOOP_MARKER = "# DataCleanr-noop: true"

_RUNNER_TEMPLATE = """\
import sys
import pandas as pd
import numpy as np

_input_path  = sys.argv[1]
_output_path = sys.argv[2]

df = pd.read_csv(_input_path)

# --- user code ---
{code}
# --- end user code ---

df.to_csv(_output_path, index=False)
"""


class ValidationResult(NamedTuple):
    safe: bool
    reason: str  # "ok" | "noop" | human-readable block reason


def validate_script(code: str) -> ValidationResult:
    """AST-based safety check for LLM-generated pandas scripts."""
    stripped = code.strip()

    if stripped.startswith(NOOP_MARKER):
        return ValidationResult(safe=True, reason="noop")

    for substr in _DENIED_SUBSTRINGS:
        if substr in code:
            return ValidationResult(safe=False, reason=f"Blocked pattern: {substr!r}")

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return ValidationResult(safe=False, reason=f"SyntaxError: {exc}")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in _DENIED_IMPORTS:
                    return ValidationResult(safe=False, reason=f"Blocked import: {alias.name!r}")

        elif isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".")[0]
            if top in _DENIED_IMPORTS:
                return ValidationResult(safe=False, reason=f"Blocked import: {node.module!r}")

        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in _DENIED_CALLS:
                return ValidationResult(safe=False, reason=f"Blocked call: {node.func.id!r}")
            if isinstance(node.func, ast.Attribute) and node.func.attr in _DENIED_ATTRS:
                return ValidationResult(safe=False, reason=f"Blocked method: {node.func.attr!r}")

    return ValidationResult(safe=True, reason="ok")


async def execute_script(
    code: str,
    input_csv_bytes: bytes,
    timeout: float = 30.0,
) -> bytes:
    """
    Run the generated pandas script in a sandboxed subprocess.

    Returns output CSV bytes.
    Raises ValueError for blocked/noop scripts.
    Raises RuntimeError on execution failure or timeout.
    """
    result = validate_script(code)
    if not result.safe:
        raise ValueError(f"BLOCKED_INSTRUCTIONS: {result.reason}")
    if result.reason == "noop":
        raise ValueError("UNINTERPRETABLE_INSTRUCTIONS")

    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = os.path.join(tmpdir, "input.csv")
        output_path = os.path.join(tmpdir, "output.csv")
        runner_path = os.path.join(tmpdir, "runner.py")

        with open(input_path, "wb") as fh:
            fh.write(input_csv_bytes)

        runner_src = _RUNNER_TEMPLATE.replace("{code}", code)
        with open(runner_path, "w") as fh:
            fh.write(runner_src)

        # Strip secrets but preserve system library paths for numpy/pandas
        _PASSTHROUGH = {"PATH", "PYTHONPATH", "HOME", "LANG", "LC_ALL",
                        "LD_LIBRARY_PATH", "LD_PRELOAD", "NIX_LD_LIBRARY_PATH"}
        _SECRET_PREFIXES = ("ANTHROPIC", "GEMINI", "REDIS", "STRIPE",
                            "DATABASE", "SENTRY", "SECRET", "KEY", "TOKEN",
                            "PASSWORD", "PASS", "RAILWAY")
        env = {
            k: v for k, v in os.environ.items()
            if k in _PASSTHROUGH or not any(k.upper().startswith(p) for p in _SECRET_PREFIXES)
        }
        env.setdefault("PATH", "/usr/bin:/bin:/usr/local/bin")

        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, runner_path, input_path, output_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=tmpdir,
                env=env,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise RuntimeError("TRANSFORM_TIMEOUT")

            if proc.returncode != 0:
                err = stderr.decode("utf-8", errors="replace")[:500]
                raise RuntimeError(f"TRANSFORM_FAILED: {err}")

            if not os.path.exists(output_path):
                raise RuntimeError("TRANSFORM_FAILED: subprocess produced no output file")

            with open(output_path, "rb") as fh:
                return fh.read()

        except (ValueError, RuntimeError):
            raise
        except Exception as exc:
            raise RuntimeError(f"TRANSFORM_FAILED: {exc}") from exc
