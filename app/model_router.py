import logging
from typing import Dict, Any
from datetime import datetime, timezone

logger = logging.getLogger("model_router")


class ModelRouter:
    """
    Dynamic Model Router allocating optimal model tier based on task complexity.
    - Lightweight tasks (routing, classification): Nova Lite / Haiku
    - Complex tasks (semantic mapping, PySpark codegen): Claude 3.5 Sonnet
    """

    MODEL_TIERS = {
        "routing": "us.amazon.nova-lite-v1:0",
        "ba_analysis": "us.amazon.nova-lite-v1:0",
        "data_profiling": "us.amazon.nova-lite-v1:0",
        "mapping_conformance": "us.anthropic.claude-3-5-sonnet-20241022-v2:0",
        "codegen": "us.anthropic.claude-3-5-sonnet-20241022-v2:0",
    }

    MODEL_PRICING = {
        "us.amazon.nova-lite-v1:0": {"input_per_1k": 0.00006, "output_per_1k": 0.00024},
        "us.anthropic.claude-3-5-sonnet-20241022-v2:0": {
            "input_per_1k": 0.003,
            "output_per_1k": 0.015,
        },
    }

    @classmethod
    def get_model_for_task(cls, task_type: str) -> str:
        """Returns the target model ARN/identifier for a given task type."""
        return cls.MODEL_TIERS.get(task_type, "us.amazon.nova-lite-v1:0")

    @classmethod
    def calculate_cost(
        cls, model_id: str, input_tokens: int, output_tokens: int
    ) -> float:
        """Calculates token cost in USD for a given invocation."""
        rates = cls.MODEL_PRICING.get(
            model_id, {"input_per_1k": 0.0001, "output_per_1k": 0.0003}
        )
        cost = (input_tokens / 1000.0) * rates["input_per_1k"] + (
            output_tokens / 1000.0
        ) * rates["output_per_1k"]
        return round(cost, 6)


class QuotaManager:
    """
    Manages daily token quotas per tenant.
    Enforces rate limits and raises HTTP 429 when daily quotas are breached.
    """

    DEFAULT_DAILY_QUOTA = 500000  # 500k tokens per tenant per day

    def __init__(self):
        # tenant_id -> {"count": int, "reset_date": str}
        self.usage_store: Dict[str, Dict[str, Any]] = {}

    def _get_today_str(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def check_quota(self, tenant_id: str) -> bool:
        """Checks if tenant has remaining quota for today."""
        today = self._get_today_str()
        record = self.usage_store.get(tenant_id, {"count": 0, "reset_date": today})
        if record["reset_date"] != today:
            record = {"count": 0, "reset_date": today}
            self.usage_store[tenant_id] = record

        return record["count"] < self.DEFAULT_DAILY_QUOTA

    def record_usage(self, tenant_id: str, tokens: int) -> int:
        """Records token usage for tenant and returns updated daily count."""
        today = self._get_today_str()
        record = self.usage_store.get(tenant_id, {"count": 0, "reset_date": today})
        if record["reset_date"] != today:
            record = {"count": 0, "reset_date": today}

        record["count"] += tokens
        self.usage_store[tenant_id] = record
        return record["count"]

    def get_tenant_quota_status(self, tenant_id: str) -> Dict[str, Any]:
        """Returns quota usage metrics for a tenant."""
        today = self._get_today_str()
        record = self.usage_store.get(tenant_id, {"count": 0, "reset_date": today})
        used = record["count"] if record["reset_date"] == today else 0
        remaining = max(0, self.DEFAULT_DAILY_QUOTA - used)
        return {
            "tenant_id": tenant_id,
            "daily_limit": self.DEFAULT_DAILY_QUOTA,
            "used_tokens": used,
            "remaining_tokens": remaining,
            "date": today,
        }
