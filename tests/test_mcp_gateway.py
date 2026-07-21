from fastapi.testclient import TestClient

try:
    from app.mcp_gateway import app as gateway_app
    from app.main import app as main_app, JOBS_STORE
except ModuleNotFoundError:
    from mcp_gateway import app as gateway_app
    from main import app as main_app, JOBS_STORE

gateway_client = TestClient(gateway_app)
main_client = TestClient(main_app)


def test_mcp_gateway_health():
    response = gateway_client.get("/mcp/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "HEALTHY"
    assert data["total_tools"] == 11
    assert "s3" in data["servers"]
    assert "postgres" in data["servers"]
    assert "databricks" in data["servers"]
    assert "vault" in data["servers"]


def test_mcp_gateway_tools_manifest_and_rbac():
    # Admin role gets all 11 tools
    admin_resp = gateway_client.get("/mcp/v1/tools", headers={"x-mcp-role": "admin"})
    assert admin_resp.status_code == 200
    assert len(admin_resp.json()["tools"]) == 11

    # Developer role gets tools excluding vault secret tool
    dev_resp = gateway_client.get("/mcp/v1/tools", headers={"x-mcp-role": "developer"})
    assert dev_resp.status_code == 200
    dev_tools = [t["name"] for t in dev_resp.json()["tools"]]
    assert "vault_fetch_secret" not in dev_tools
    assert "s3_discover_landing_bucket" in dev_tools


def test_mcp_gateway_call_tool():
    call_resp = gateway_client.post(
        "/mcp/v1/call",
        json={
            "name": "dlt_generate_pipeline_spec",
            "arguments": {"entity_name": "transaction"},
        },
        headers={"x-mcp-role": "developer"},
    )
    assert call_resp.status_code == 200
    res = call_resp.json()
    assert res["status"] == "SUCCESS"
    assert "pipeline_spec" in res["result"]


def test_async_pipeline_job_status_endpoint(monkeypatch):
    monkeypatch.setenv("DEV_BYPASS_AUTH", "true")
    job_id = "test-job-999"
    JOBS_STORE[job_id] = {
        "job_id": job_id,
        "status": "COMPLETED",
        "result": {"status": "SUCCESS", "records_processed": 100},
    }

    # Test status endpoint with DEV_BYPASS_AUTH set
    status_resp = main_client.get(
        f"/pipeline/status/{job_id}",
        headers={"Authorization": "Bearer dev_token"},
    )
    assert status_resp.status_code == 200
    data = status_resp.json()
    assert data["status"] == "COMPLETED"
    assert data["result"]["records_processed"] == 100
