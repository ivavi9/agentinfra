try:
    from app.model_router import ModelRouter, QuotaManager
except ModuleNotFoundError:
    from model_router import ModelRouter, QuotaManager


def test_model_router_allocation_and_cost():
    # Routing/classification gets lightweight model
    route_model = ModelRouter.get_model_for_task("routing")
    assert "nova-lite" in route_model

    # Mapping/codegen gets frontier Claude model
    codegen_model = ModelRouter.get_model_for_task("codegen")
    assert "claude-3-5-sonnet" in codegen_model

    # Calculate cost
    cost = ModelRouter.calculate_cost(
        codegen_model, input_tokens=1000, output_tokens=500
    )
    assert cost > 0.0
    assert isinstance(cost, float)


def test_quota_manager():
    qm = QuotaManager()
    tenant_id = "tenant-test-123"

    # Initial check should pass
    assert qm.check_quota(tenant_id) is True

    # Record tokens
    qm.record_usage(tenant_id, 100000)
    status = qm.get_tenant_quota_status(tenant_id)
    assert status["used_tokens"] == 100000
    assert status["remaining_tokens"] == 400000

    # Exceed limit
    qm.record_usage(tenant_id, 450000)
    assert qm.check_quota(tenant_id) is False
