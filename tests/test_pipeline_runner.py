import hashlib
from unittest.mock import MagicMock

try:
    from app.pipeline_runner import PipelineRunner
except ModuleNotFoundError:
    from pipeline_runner import PipelineRunner


def test_pipeline_runner_sha256_hash():
    val = "CUST-10001"
    hashed = hashlib.sha256(val.encode("utf-8")).hexdigest()
    assert len(hashed) == 64
    assert hashed == "2a39d5d8180916eebe5f472a0b6db50d4390897053f627ef7c6beefe67e464be"


def test_pipeline_runner_run_conformance_with_mock_db():
    db_config = {
        "db_host": "localhost",
        "db_port": "5432",
        "db_name": "testdb",
        "db_user": "postgres",
        "db_password": "secretpassword",
    }

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    mappings = [
        {
            "source_column": "txn_id",
            "target_attribute": "AC_TXN_ID",
            "transform_rule": "DIRECT",
        },
        {
            "source_column": "cust_id",
            "target_attribute": "CUSTOMER_ID_HASH",
            "transform_rule": "SHA256",
        },
        {
            "source_column": "amount",
            "target_attribute": "TRANSACTION_AMOUNT",
            "transform_rule": "CAST(amount AS DECIMAL(18,2))",
        },
    ]

    raw_records = [{"txn_id": "T-100", "cust_id": "C-1", "amount": "150.50"}]

    runner = PipelineRunner(db_config)
    runner._get_connection = MagicMock(return_value=mock_conn)
    mock_conn.__enter__.return_value = mock_conn
    runner.download_s3_json = MagicMock(return_value=raw_records)

    res = runner.run_conformance(
        entity_name="transaction", mappings=mappings, bucket="test-bucket"
    )

    assert res["status"] == "SUCCESS"
    assert res["records_processed"] == 1
    assert res["silver_table"] == "silver_transaction"
    assert mock_cursor.execute.called


def test_pipeline_runner_explicit_pk_surrogate_key():
    db_config = {
        "db_host": "localhost",
        "db_port": "5432",
        "db_name": "testdb",
        "db_user": "postgres",
        "db_password": "secretpassword",
    }
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    # Existing PK query returns 'MY_EXPLICIT_PK'
    mock_cursor.fetchone.return_value = ("MY_EXPLICIT_PK",)

    mappings = [
        {
            "source_column": "id",
            "target_attribute": "OTHER_ID",
            "transform_rule": "DIRECT",
        },
        {
            "source_column": "key",
            "target_attribute": "MY_EXPLICIT_PK",
            "transform_rule": "SHA256",
            "is_surrogate_key": True,
        },
    ]
    raw_records = [{"id": "1", "key": "k1"}]

    runner = PipelineRunner(db_config)
    runner._get_connection = MagicMock(return_value=mock_conn)
    mock_conn.__enter__.return_value = mock_conn
    runner.download_s3_json = MagicMock(return_value=raw_records)

    res = runner.run_conformance(
        entity_name="test", mappings=mappings, bucket="test-bucket"
    )
    assert res["status"] == "SUCCESS"
    assert mock_cursor.execute.called
