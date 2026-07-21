import os
from fastapi.testclient import TestClient

# Set environment before importing main app
os.environ["DEV_BYPASS_AUTH"] = "false"

try:
    from app.main import app
except ModuleNotFoundError:
    from main import app

client = TestClient(app)


def test_unauthenticated_chat_route_returns_401():
    response = client.post("/chat", json={"prompt": "hello"})
    assert response.status_code == 401
    assert "Missing authorization header" in response.json()["detail"]


def test_unauthenticated_pipeline_analyse_returns_401():
    response = client.post("/pipeline/analyse", json={"brd_document": "sample BRD"})
    assert response.status_code == 401


def test_unauthenticated_pipeline_approve_returns_401():
    response = client.post(
        "/pipeline/approve", json={"session_id": "s1", "mapping_matrix": []}
    )
    assert response.status_code == 401


def test_unauthenticated_pipeline_run_returns_401():
    response = client.post(
        "/pipeline/run", json={"session_id": "s1", "entity_name": "customer"}
    )
    assert response.status_code == 401


def test_invalid_header_format_returns_401():
    response = client.post(
        "/chat", json={"prompt": "hello"}, headers={"Authorization": "Basic 12345"}
    )
    assert response.status_code == 401
    assert "Invalid authorization header format" in response.json()["detail"]


def test_dev_bypass_auth():
    os.environ["DEV_BYPASS_AUTH"] = "true"
    # When bypass is true, auth should succeed without token
    # (will return 503 if agent_orchestrator uninitialized, but NOT 401)
    response = client.post("/chat", json={"prompt": "hello"})
    assert response.status_code != 401
    os.environ["DEV_BYPASS_AUTH"] = "false"


def test_config_endpoint_accessible_without_auth():
    response = client.get("/config")
    assert response.status_code == 200
    data = response.json()
    assert "cognito_client_id" in data
    assert "aws_region" in data
