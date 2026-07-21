from app.eval_harness import MappingEvalHarness, GOLDEN_BRD_FIXTURE


def test_eval_harness_perfect_score():
    predicted = [
        {"source_column": "txn_id", "target_column": "AC_TXN_ID"},
        {"source_column": "customer_id", "target_column": "CUSTOMER_ID_HASH"},
        {"source_column": "ac_id", "target_column": "AC_ID"},
        {"source_column": "amount", "target_column": "TRANSACTION_AMOUNT"},
        {"source_column": "timestamp", "target_column": "TRANSACTION_TIMESTAMP"},
    ]
    res = MappingEvalHarness.evaluate_mapping_accuracy(predicted, GOLDEN_BRD_FIXTURE)
    assert res["precision"] == 1.0
    assert res["recall"] == 1.0
    assert res["f1_score"] == 1.0
    assert res["passed"] is True


def test_eval_harness_partial_score():
    predicted = [
        {"source_column": "txn_id", "target_column": "AC_TXN_ID"},
        {"source_column": "customer_id", "target_column": "WRONG_COLUMN"},
    ]
    res = MappingEvalHarness.evaluate_mapping_accuracy(predicted, GOLDEN_BRD_FIXTURE)
    assert res["correct_matches"] == 1
    assert res["passed"] is False
