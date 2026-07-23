try:
    from app.metrics import (
        increment_route,
        increment_tokens,
        record_pipeline_run,
        get_prometheus_metrics,
    )
    from app.lineage_viewer import LineageGraphService
    from app.document_parser import BRDDocumentParser
except ModuleNotFoundError:
    from metrics import (
        increment_route,
        increment_tokens,
        record_pipeline_run,
        get_prometheus_metrics,
    )
    from lineage_viewer import LineageGraphService
    from document_parser import BRDDocumentParser


def test_prometheus_metrics():
    increment_route("CODE")
    increment_tokens(50)
    record_pipeline_run("completed")

    prom_text = get_prometheus_metrics()
    assert "agent_routes_total" in prom_text
    assert "llm_token_chunks_total" in prom_text


def test_lineage_graph_generation():
    mappings = [
        {
            "source_column": "cust_id",
            "target_attribute": "IP_ID",
            "transform_rule": "DIRECT",
        },
        {
            "source_column": "txn_amt",
            "target_attribute": "TRANSACTION_AMOUNT",
            "transform_rule": "CAST(NUMERIC)",
        },
    ]

    res = LineageGraphService.generate_lineage(
        "transaction", mappings, tenant_id="tenant-acme"
    )
    assert res["status"] == "SUCCESS"
    assert res["summary"]["total_nodes"] > 0
    assert res["summary"]["mapped_fields"] == 2


def test_brd_document_parser():
    brd_text = """
    Entity Name: Financial_Transaction
    - Field customer_id maps to involved party key
    - Field amount maps to transaction amount
    """
    res = BRDDocumentParser.parse_brd_content(brd_text)
    assert res["status"] == "SUCCESS"
    assert res["entity_name"] == "financial_transaction"
    assert res["requirement_count"] == 2
