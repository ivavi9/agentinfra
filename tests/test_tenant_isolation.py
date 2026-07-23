from fastapi.testclient import TestClient

try:
    from app.tenant_governance import PIIRedactor, TenantIsolationManager
    from app.main import (
        app as main_app,
        JOBS_STORE,
        AUDIT_STORE,
    )
except ModuleNotFoundError:
    from tenant_governance import PIIRedactor, TenantIsolationManager
    from main import app as main_app, JOBS_STORE, AUDIT_STORE

client = TestClient(main_app)


def test_pii_redactor_text_and_dict():
    # Test text redaction
    sample_text = (
        "User SSN is 123-45-6789, email is test@domain.com, and phone is 555-123-4567."
    )
    redacted = PIIRedactor.redact_text(sample_text)
    assert "[REDACTED_SSN]" in redacted
    assert "[REDACTED_EMAIL]" in redacted
    assert "[REDACTED_PHONE]" in redacted
    assert "123-45-6789" not in redacted

    # Test dict recursion
    data = {
        "user": "Alice",
        "ssn": "987-65-4321",
        "nested": {"contact_email": "alice@bank.org"},
    }
    red_dict = PIIRedactor.redact_dict(data)
    assert red_dict["ssn"] == "[REDACTED_SSN]"
    assert red_dict["nested"]["contact_email"] == "[REDACTED_EMAIL]"


def test_tenant_isolation_job_access(monkeypatch):
    monkeypatch.setenv("DEV_BYPASS_AUTH", "true")

    # Create job for tenant-alpha
    job_id = "job-alpha-001"
    JOBS_STORE[job_id] = {
        "job_id": job_id,
        "status": "COMPLETED",
        "user_id": "dev_user",
        "tenant_id": "tenant-alpha",
        "result": {"status": "SUCCESS"},
    }

    # Tenant-alpha can access their job
    resp_alpha = client.get(
        f"/pipeline/status/{job_id}",
        headers={"Authorization": "Bearer token", "X-Tenant-ID": "tenant-alpha"},
    )
    assert resp_alpha.status_code == 200
    assert resp_alpha.json()["tenant_id"] == "tenant-alpha"

    # Tenant-beta is denied access (403)
    resp_beta = client.get(
        f"/pipeline/status/{job_id}",
        headers={"Authorization": "Bearer token", "X-Tenant-ID": "tenant-beta"},
    )
    assert resp_beta.status_code == 403
    assert "Access denied" in resp_beta.json()["detail"]


def test_audit_logs_endpoint(monkeypatch):
    monkeypatch.setenv("DEV_BYPASS_AUTH", "true")
    AUDIT_STORE.clear()

    # Create audit event for tenant-finance
    entry = TenantIsolationManager.create_audit_entry(
        tenant_id="tenant-finance",
        actor="dev_user",
        action="PIPELINE_ANALYSE",
        resource="/pipeline/analyse",
        payload={"session_id": "s1"},
    )
    AUDIT_STORE.append(entry)

    # Fetch audit logs for tenant-finance
    resp = client.get(
        "/audit/logs",
        headers={"Authorization": "Bearer token", "X-Tenant-ID": "tenant-finance"},
    )
    assert resp.status_code == 200
    logs = resp.json()["logs"]
    assert len(logs) == 1
    assert logs[0]["tenant_id"] == "tenant-finance"
    assert logs[0]["action"] == "PIPELINE_ANALYSE"


def test_rls_ddl_and_tenant_session_execution():
    class DummyCursor:
        def __init__(self):
            self.executed = []

        def execute(self, sql, params=None):
            self.executed.append((sql, params))

    cur = DummyCursor()
    TenantIsolationManager.enable_table_rls(cur, "silver_tenant_alpha_transaction")
    assert len(cur.executed) == 4
    assert "ENABLE ROW LEVEL SECURITY" in cur.executed[1][0]
    assert "CREATE POLICY tenant_isolation_policy" in cur.executed[3][0]

    cur_session = DummyCursor()
    TenantIsolationManager.set_tenant_session(cur_session, "tenant-finance")
    assert len(cur_session.executed) == 1
    assert "app.current_tenant" in cur_session.executed[0][0]
    assert cur_session.executed[0][1] == ("tenant-finance",)
