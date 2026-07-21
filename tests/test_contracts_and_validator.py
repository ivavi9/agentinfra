import pytest
from app.contracts import MappingMatrixContract, TransformDSL
from app.validator import PipelineValidator, MappingValidationError


def test_mapping_matrix_contract_validation():
    valid_data = {
        "mappings": [
            {
                "source_table": "bronze_transaction",
                "source_column": "txn_id",
                "target_table": "silver_transaction",
                "target_column": "ac_txn_id",
                "transformation_rule": "DIRECT",
                "transform_dsl": "DIRECT",
                "is_surrogate_key": True,
            }
        ]
    }
    contract = MappingMatrixContract(**valid_data)
    assert len(contract.mappings) == 1
    assert contract.mappings[0].transform_dsl == TransformDSL.DIRECT


def test_pipeline_validator_detects_target_collision():
    bronze_schema = {"columns": ["id", "val1", "val2"]}
    mapping_matrix = [
        {"source_column": "val1", "target_column": "amount"},
        {"source_column": "val2", "target_column": "amount"},  # Collision!
    ]
    with pytest.raises(MappingValidationError) as exc:
        PipelineValidator.validate_mapping_matrix(bronze_schema, mapping_matrix)
    assert "Target column name collisions detected" in str(exc.value)


def test_pipeline_validator_valid_coverage():
    bronze_schema = {"columns": ["id", "val1"]}
    mapping_matrix = [
        {"source_column": "id", "target_column": "ac_id"},
        {"source_column": "val1", "target_column": "amount"},
    ]
    result = PipelineValidator.validate_mapping_matrix(bronze_schema, mapping_matrix)
    assert result["valid"] is True
    assert result["coverage_pct"] == 100.0
