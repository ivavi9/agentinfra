from typing import List, Dict, Any

GOLDEN_BRD_FIXTURE = {
    "brd_title": "Retail Banking Core Transaction Ingestion",
    "description": "Ingest transaction feed containing txn_id, customer_id, ac_id, amount, timestamp",
    "raw_columns": ["txn_id", "customer_id", "ac_id", "amount", "timestamp"],
    "expected_mappings": [
        {"source_column": "txn_id", "target_column": "AC_TXN_ID"},
        {"source_column": "customer_id", "target_column": "CUSTOMER_ID_HASH"},
        {"source_column": "ac_id", "target_column": "AC_ID"},
        {"source_column": "amount", "target_column": "TRANSACTION_AMOUNT"},
        {"source_column": "timestamp", "target_column": "TRANSACTION_TIMESTAMP"},
    ],
}


class MappingEvalHarness:
    """Evaluation harness for assessing agent mapping accuracy against golden baseline fixtures."""

    @staticmethod
    def evaluate_mapping_accuracy(
        predicted_mappings: List[Dict[str, Any]],
        golden_fixture: Dict[str, Any] = GOLDEN_BRD_FIXTURE,
    ) -> Dict[str, Any]:
        expected = golden_fixture["expected_mappings"]
        expected_map = {
            item["source_column"].lower(): item["target_column"].upper()
            for item in expected
        }

        predicted_map = {}
        for item in predicted_mappings:
            src = (item.get("source_column") or "").lower()
            tgt = (
                item.get("target_column") or item.get("target_attribute") or ""
            ).upper()
            if src:
                predicted_map[src] = tgt

        correct_matches = 0
        total_expected = len(expected_map)

        for src_col, exp_target in expected_map.items():
            pred_target = predicted_map.get(src_col)
            if pred_target == exp_target:
                correct_matches += 1

        precision = (correct_matches / len(predicted_map)) if predicted_map else 0.0
        recall = (correct_matches / total_expected) if total_expected else 0.0
        f1 = (
            (2 * precision * recall / (precision + recall))
            if (precision + recall) > 0
            else 0.0
        )

        return {
            "total_expected": total_expected,
            "total_predicted": len(predicted_map),
            "correct_matches": correct_matches,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1_score": round(f1, 4),
            "passed": f1 >= 0.80,
        }
