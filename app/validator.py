from typing import List


class MappingValidationError(Exception):
    pass


class PipelineValidator:
    """Deterministic validation node executed before DAB codegen and pipeline execution."""

    @staticmethod
    def validate_mapping_matrix(
        bronze_schema: dict, mapping_matrix: List[dict]
    ) -> dict:
        errors = []
        warnings = []

        # 1. Column Coverage Check
        raw_columns = set()
        for col in bronze_schema.get("columns", []):
            if isinstance(col, dict):
                raw_columns.add(col.get("name"))
            else:
                raw_columns.add(str(col))

        mapped_sources = set()
        target_columns = []

        for m in mapping_matrix:
            src = m.get("source_column")
            tgt = m.get("target_column") or m.get("target_attribute")
            if src:
                mapped_sources.add(src)
            if tgt:
                target_columns.append(tgt.lower())

        unmapped = raw_columns - mapped_sources
        if unmapped:
            warnings.append(f"Unmapped source columns found: {list(unmapped)}")

        # 2. Target Column Collision Check
        duplicates = [
            col for col in set(target_columns) if target_columns.count(col) > 1
        ]
        if duplicates:
            errors.append(f"Target column name collisions detected: {duplicates}")

        # 3. Rule Validity Check
        for m in mapping_matrix:
            rule = m.get("transformation_rule") or m.get("transform_rule") or ""
            if not rule:
                warnings.append(
                    f"Empty transformation rule for column: {m.get('source_column')}"
                )

        if errors:
            raise MappingValidationError(
                f"Deterministic validation failed: {'; '.join(errors)}"
            )

        return {
            "valid": True,
            "errors": errors,
            "warnings": warnings,
            "coverage_pct": (
                (len(mapped_sources) / len(raw_columns) * 100.0)
                if raw_columns
                else 100.0
            ),
        }
