import re
import json
import logging
import hashlib
from datetime import datetime, timezone
from typing import Dict, Any, Optional

logger = logging.getLogger("tenant_governance")


class PIIRedactor:
    """
    Pre-prompt PII Redactor utility. Sanitizes sensitive Personal Identifiable Information
    (SSNs, Credit Card numbers, Emails, Phone Numbers) from user prompts and payload JSONs
    before sending data to external LLMs.
    """

    PATTERNS = {
        "SSN": (r"\b\d{3}-\d{2}-\d{4}\b", "[REDACTED_SSN]"),
        "CREDIT_CARD": (
            r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13})\b",
            "[REDACTED_CC]",
        ),
        "EMAIL": (
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
            "[REDACTED_EMAIL]",
        ),
        "PHONE": (
            r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
            "[REDACTED_PHONE]",
        ),
    }

    @classmethod
    def redact_text(cls, text: str) -> str:
        """Redacts sensitive PII from a plain text string."""
        if not text:
            return text
        sanitized = text
        for p_name, (pattern, replacement) in cls.PATTERNS.items():
            sanitized = re.sub(pattern, replacement, sanitized)
        return sanitized

    @classmethod
    def redact_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively redacts PII strings within a dictionary."""
        if not isinstance(data, dict):
            return data
        sanitized: Dict[str, Any] = {}
        for k, v in data.items():
            if isinstance(v, str):
                sanitized[k] = cls.redact_text(v)
            elif isinstance(v, dict):
                sanitized[k] = cls.redact_dict(v)
            elif isinstance(v, list):
                sanitized[k] = [
                    (
                        cls.redact_dict(item)
                        if isinstance(item, dict)
                        else cls.redact_text(item) if isinstance(item, str) else item
                    )
                    for item in v
                ]
            else:
                sanitized[k] = v
        return sanitized


class TenantIsolationManager:
    """
    Manages multi-tenant Row-Level Security (RLS) and immutable audit log storage.
    """

    AUDIT_TABLE_DDL = """
    CREATE TABLE IF NOT EXISTS audit_logs (
        audit_id VARCHAR(64) PRIMARY KEY,
        tenant_id VARCHAR(64) NOT NULL,
        actor VARCHAR(128) NOT NULL,
        action VARCHAR(64) NOT NULL,
        resource VARCHAR(255) NOT NULL,
        input_hash VARCHAR(64) NOT NULL,
        payload JSONB,
        timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_audit_tenant ON audit_logs(tenant_id);
    """

    RLS_DDL_TEMPLATE = """
    ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation_policy ON {table_name};
    CREATE POLICY tenant_isolation_policy ON {table_name}
        USING (tenant_id = current_setting('app.current_tenant', true))
        WITH CHECK (tenant_id = current_setting('app.current_tenant', true));
    """

    @staticmethod
    def compute_hash(payload: Any) -> str:
        """Generates SHA-256 hash of payload for audit integrity verification."""
        raw = (
            json.dumps(payload, sort_keys=True)
            if isinstance(payload, (dict, list))
            else str(payload)
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @classmethod
    def create_audit_entry(
        cls,
        tenant_id: str,
        actor: str,
        action: str,
        resource: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Creates a structured audit log object."""
        audit_id = f"aud-{hashlib.md5(f'{tenant_id}:{actor}:{datetime.now(timezone.utc).timestamp()}'.encode()).hexdigest()[:10]}"
        sanitized_payload = PIIRedactor.redact_dict(payload or {})
        input_hash = cls.compute_hash(sanitized_payload)

        return {
            "audit_id": audit_id,
            "tenant_id": tenant_id,
            "actor": actor,
            "action": action,
            "resource": resource,
            "input_hash": input_hash,
            "payload": sanitized_payload,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @classmethod
    def enable_table_rls(cls, cur: Any, table_name: str) -> None:
        """Executes DDL to enable Row-Level Security (RLS) on a target PostgreSQL table."""
        try:
            cur.execute(
                f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(64);"
            )
            cur.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY;")
            cur.execute(
                f"DROP POLICY IF EXISTS tenant_isolation_policy ON {table_name};"
            )
            cur.execute(
                f"""
                CREATE POLICY tenant_isolation_policy ON {table_name}
                    USING (tenant_id = current_setting('app.current_tenant', true))
                    WITH CHECK (tenant_id = current_setting('app.current_tenant', true));
                """
            )
            logger.info(f"Successfully enabled RLS policy on table: {table_name}")
        except Exception as e:
            logger.warning(f"Could not apply RLS DDL to {table_name}: {e}")

    @classmethod
    def set_tenant_session(cls, cur: Any, tenant_id: str) -> None:
        """Sets the PostgreSQL session variable app.current_tenant for RLS enforcement."""
        try:
            cur.execute(
                "SELECT set_config('app.current_tenant', %s, true);", (tenant_id,)
            )
        except Exception as e:
            logger.warning(f"Could not set app.current_tenant session config: {e}")
