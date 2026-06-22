"""
/transform and /preview route tests.
LLM calls and Redis are mocked — actual LLM quality is tested in tests/evals/.
"""
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest

CSV_CLEAN = b"name,email\nAlice,a@x.com\nBob,b@x.com\n"
CSV_WITH_NULLS = b"name,email,score\nAlice,a@x.com,90\nBob,,80\nCarol,c@x.com,\n"
CLEAN_CODE = "df = df.dropna()"


def _mock_llm(code: str):
    return patch("app.routes._call_llm", new=AsyncMock(return_value=code))


def _mock_rate_limit(allowed: bool = True, used: int = 0, limit: int = 500):
    """Patch Redis-backed rate limit so tests don't need a real Redis."""
    return patch(
        "app.routes.check_row_budget",
        new=AsyncMock(return_value=(allowed, used, limit)),
    )


def test_transform_happy_path(client, registered_user):
    _, api_key = registered_user
    with _mock_rate_limit(), _mock_llm(CLEAN_CODE), patch("app.routes.commit_row_usage", new=AsyncMock()):
        r = client.post(
            "/transform",
            headers={"X-API-Key": api_key},
            data={"instructions": "remove rows with missing values"},
            files={"file": ("data.csv", CSV_WITH_NULLS, "text/csv")},
        )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert b"Alice" in r.content
    assert b"Bob" not in r.content   # Bob has null email


def test_transform_returns_summary_header(client, registered_user):
    _, api_key = registered_user
    with _mock_rate_limit(), _mock_llm(CLEAN_CODE), patch("app.routes.commit_row_usage", new=AsyncMock()):
        r = client.post(
            "/transform",
            headers={"X-API-Key": api_key},
            data={"instructions": "remove nulls"},
            files={"file": ("data.csv", CSV_WITH_NULLS, "text/csv")},
        )
    assert "X-DataCleanr-Summary" in r.headers


def test_transform_empty_instructions(client, registered_user):
    _, api_key = registered_user
    r = client.post(
        "/transform",
        headers={"X-API-Key": api_key},
        data={"instructions": "   "},
        files={"file": ("data.csv", CSV_CLEAN, "text/csv")},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "EMPTY_INSTRUCTIONS"


def test_transform_file_too_large(client, registered_user):
    _, api_key = registered_user
    big = b"a,b\n" + b"1,2\n" * (3 * 1024 * 1024)  # ~12 MB — above 10 MB limit
    r = client.post(
        "/transform",
        headers={"X-API-Key": api_key},
        data={"instructions": "do something"},
        files={"file": ("big.csv", big, "text/csv")},
    )
    assert r.status_code == 413


def test_transform_blocked_instructions(client, registered_user):
    _, api_key = registered_user
    with _mock_rate_limit(), _mock_llm("import os; os.system('rm -rf /')"):
        r = client.post(
            "/transform",
            headers={"X-API-Key": api_key},
            data={"instructions": "delete everything"},
            files={"file": ("data.csv", CSV_CLEAN, "text/csv")},
        )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "BLOCKED_INSTRUCTIONS"


def test_transform_llm_noop(client, registered_user):
    _, api_key = registered_user
    with _mock_rate_limit(), _mock_llm("# DataCleanr-noop: true"):
        r = client.post(
            "/transform",
            headers={"X-API-Key": api_key},
            data={"instructions": "$$$$@@@"},
            files={"file": ("data.csv", CSV_CLEAN, "text/csv")},
        )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "UNINTERPRETABLE_INSTRUCTIONS"


def test_preview_returns_at_most_10_rows(client, registered_user):
    _, api_key = registered_user
    big_csv = b"id\n" + b"\n".join(str(i).encode() for i in range(50)) + b"\n"
    with _mock_llm("pass  # df unchanged"):
        r = client.post(
            "/preview",
            headers={"X-API-Key": api_key},
            data={"instructions": "do nothing"},
            files={"file": ("data.csv", big_csv, "text/csv")},
        )
    assert r.status_code == 200
    rows = r.content.strip().split(b"\n")
    assert len(rows) <= 11  # 1 header + max 10 data rows


def test_preview_no_quota_deducted(client, registered_user):
    """Preview should not touch the rate-limit counter."""
    _, api_key = registered_user
    with patch("app.routes.commit_row_usage", new=AsyncMock()) as mock_commit:
        with _mock_llm("pass"):
            client.post(
                "/preview",
                headers={"X-API-Key": api_key},
                data={"instructions": "do nothing"},
                files={"file": ("data.csv", CSV_CLEAN, "text/csv")},
            )
        mock_commit.assert_not_called()
