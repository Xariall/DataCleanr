from tests.conftest import CSV_FIXTURE


def test_register_success(client):
    r = client.post("/register", json={"email": "new@example.com"})
    assert r.status_code == 200
    data = r.json()
    assert data["api_key"].startswith("dc_")
    assert "message" in data


def test_register_duplicate(client, registered_user):
    email, _ = registered_user
    r = client.post("/register", json={"email": email})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "EMAIL_EXISTS"


def test_register_invalid_email(client):
    r = client.post("/register", json={"email": "not-an-email"})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "INVALID_EMAIL"


def test_register_missing_email(client):
    r = client.post("/register", json={})
    assert r.status_code == 400


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_landing_page(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "DataCleanr" in r.text
    assert "curl" in r.text


def test_upgrade_no_link(client, monkeypatch):
    monkeypatch.delenv("STRIPE_PAYMENT_LINK", raising=False)
    r = client.get("/upgrade", follow_redirects=False)
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "UPGRADE_UNAVAILABLE"


def test_upgrade_with_link(client, monkeypatch):
    monkeypatch.setenv("STRIPE_PAYMENT_LINK", "https://buy.stripe.com/test_abc")
    r = client.get("/upgrade", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "https://buy.stripe.com/test_abc"


def test_transform_no_api_key(client):
    r = client.post("/transform", data={"instructions": "remove nulls"},
                    files={"file": ("data.csv", CSV_FIXTURE, "text/csv")})
    assert r.status_code == 401
    assert r.json()["code"] == "MISSING_API_KEY"


def test_transform_invalid_api_key(client):
    r = client.post(
        "/transform",
        headers={"X-API-Key": "dc_invalid"},
        data={"instructions": "remove nulls"},
        files={"file": ("data.csv", CSV_FIXTURE, "text/csv")},
    )
    assert r.status_code == 401
    assert r.json()["code"] == "INVALID_API_KEY"


def test_preview_no_api_key(client):
    r = client.post("/preview", data={"instructions": "remove nulls"},
                    files={"file": ("data.csv", CSV_FIXTURE, "text/csv")})
    assert r.status_code == 401


def test_me_no_api_key(client):
    r = client.get("/me")
    assert r.status_code == 401


def test_me_returns_user_info(client, registered_user):
    email, api_key = registered_user
    r = client.get("/me", headers={"X-API-Key": api_key})
    assert r.status_code == 200
    data = r.json()
    assert data["email"] == email
    assert data["tier"] == "FREE"
    assert "rows_used_today" in data
    assert "rows_limit_today" in data
    assert data["upgrade_url"] == "/upgrade"


def test_stats_no_secret(client, monkeypatch):
    monkeypatch.setenv("ADMIN_SECRET", "s3cr3t")
    r = client.get("/stats")
    assert r.status_code == 403


def test_stats_with_secret(client, monkeypatch):
    monkeypatch.setenv("ADMIN_SECRET", "s3cr3t")
    r = client.get("/stats", headers={"X-Admin-Secret": "s3cr3t"})
    assert r.status_code == 200
    data = r.json()
    assert "total_users" in data
    assert "transforms_today" in data
    assert "rows_processed_today" in data
