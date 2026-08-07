from fastapi.testclient import TestClient

from repo_evidence.main import app


def test_liveness_and_request_id() -> None:
    with TestClient(app) as client:
        response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["x-request-id"]
    assert response.headers["x-robots-tag"] == "noindex, nofollow"


def test_home_and_openapi_are_available() -> None:
    with TestClient(app) as client:
        home = client.get("/")
        schema = client.get("/openapi.json")
    assert home.status_code == 200
    assert "Качество проекта" in home.text
    assert schema.status_code == 200
    assert "/api/v1/analyses" in schema.json()["paths"]


def test_validation_errors_use_problem_details() -> None:
    with TestClient(app) as client:
        response = client.post("/api/v1/analyses", json={"repository_url": "not-a-url"})
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "validation_error"


def test_hidden_ui_states_cannot_be_overridden_by_component_styles() -> None:
    with TestClient(app) as client:
        css = client.get("/static/app.css")
        script = client.get("/static/report.js")
        page = client.get("/reports/00000000-0000-0000-0000-000000000001")
    assert css.status_code == 200
    assert "[hidden] { display: none !important; }" in css.text
    assert "function setView(active)" in script.text
    assert "consecutiveErrors >= 3" in script.text
    assert 'id="report" hidden' in page.text
    assert 'id="failure" class="state-panel failure" hidden' in page.text
    assert 'id="worker-hint" class="worker-hint" hidden' in page.text
