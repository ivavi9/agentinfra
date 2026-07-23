from fastapi.testclient import TestClient

try:
    from app.compliance_manager import CompliancePostureManager
    from app.main import app as main_app
except ModuleNotFoundError:
    from compliance_manager import CompliancePostureManager
    from main import app as main_app

client = TestClient(main_app)


def test_compliance_posture_manager():
    posture = CompliancePostureManager.get_compliance_posture()
    assert posture["status"] == "COMPLIANT"
    assert posture["framework"] == "SOC2_TYPE2_READY"
    assert len(posture["controls"]) == 6


def test_compliance_posture_endpoint(monkeypatch):
    monkeypatch.setenv("DEV_BYPASS_AUTH", "true")
    resp = client.get(
        "/compliance/posture",
        headers={"Authorization": "Bearer token"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "COMPLIANT"
    assert data["verified_controls"] == 6


def test_model_quota_endpoint(monkeypatch):
    monkeypatch.setenv("DEV_BYPASS_AUTH", "true")
    resp = client.get(
        "/model/quota",
        headers={"Authorization": "Bearer token", "X-Tenant-ID": "tenant-finance"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["tenant_id"] == "tenant-finance"
    assert data["daily_limit"] == 500000
