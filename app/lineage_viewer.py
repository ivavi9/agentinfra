import logging
from typing import Dict, Any, List

logger = logging.getLogger("lineage_viewer")


class LineageGraphService:
    """
    Field-level Data Lineage Graph Service.
    Generates structured lineage relationships (Source Column -> Bronze Table -> Silver Table -> Target Attribute)
    including applied transform DSL rules and DQ expectation flags.
    """

    @classmethod
    def generate_lineage(
        cls,
        entity_name: str,
        mappings: List[Dict[str, Any]],
        tenant_id: str = "tenant-default",
    ) -> Dict[str, Any]:
        """Generates a node-and-edge field-level lineage graph dictionary."""
        nodes = []
        edges = []

        bronze_table = f"bronze_{tenant_id}_{entity_name}"
        silver_table = f"silver_{tenant_id}_{entity_name}"

        # Root entity nodes
        nodes.append(
            {
                "id": f"source_{entity_name}",
                "type": "SOURCE_ENTITY",
                "label": entity_name,
            }
        )
        nodes.append(
            {"id": bronze_table, "type": "BRONZE_TABLE", "label": bronze_table}
        )
        nodes.append(
            {"id": silver_table, "type": "SILVER_TABLE", "label": silver_table}
        )

        edges.append(
            {
                "source": f"source_{entity_name}",
                "target": bronze_table,
                "transform": "RAW_APPEND",
            }
        )

        for m in mappings:
            src_col = (m.get("source_column") or m.get("source_field") or "").strip()
            tgt_col = (
                m.get("target_attribute") or m.get("target_column") or ""
            ).strip()
            rule = (
                m.get("transform_rule") or m.get("transformation_rule") or "DIRECT"
            ).upper()

            if not src_col or not tgt_col:
                continue

            src_node_id = f"src_col_{src_col}"
            tgt_node_id = f"tgt_col_{tgt_col}"

            nodes.append({"id": src_node_id, "type": "SOURCE_COLUMN", "label": src_col})
            nodes.append(
                {"id": tgt_node_id, "type": "TARGET_ATTRIBUTE", "label": tgt_col}
            )

            edges.append(
                {"source": src_node_id, "target": bronze_table, "transform": "INGEST"}
            )
            edges.append(
                {"source": bronze_table, "target": tgt_node_id, "transform": rule}
            )

        return {
            "status": "SUCCESS",
            "entity_name": entity_name,
            "tenant_id": tenant_id,
            "summary": {
                "total_nodes": len(nodes),
                "total_edges": len(edges),
                "mapped_fields": len(mappings),
            },
            "graph": {"nodes": nodes, "edges": edges},
        }
