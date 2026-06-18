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
