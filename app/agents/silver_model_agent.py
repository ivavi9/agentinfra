import json
import logging
from langchain_core.messages import SystemMessage, HumanMessage
from canonical_store import CanonicalModelStore

logger = logging.getLogger("silver_model")


class SilverModelAgent:
    def __init__(self, llm):
        self.llm = llm
        self.store = CanonicalModelStore()

    def conform_model(self, bronze_schema: dict) -> dict:
        # Retrieve grounded candidates for each column in the bronze schema
        grounded_candidates = {}
        columns = bronze_schema.get("columns", [])
        if isinstance(columns, list):
            for col in columns:
                col_name = col.get("name") if isinstance(col, dict) else str(col)
                grounded_candidates[col_name] = self.store.search_attributes(col_name)

        prompt = f"""You are an expert Enterprise Data Architect.
Conform the provided Bronze layer schema to standard enterprise canonical model structures using GROUNDED candidates.

Grounded Candidate Attributes retrieved from Canonical Reference Store:
{json.dumps(grounded_candidates, indent=2)}

Instructions:
1. Select target attributes strictly from the provided grounded candidates whenever possible.
2. For each attribute mapping, include the confidence score (0.0 to 1.0) based on ground-truth alignment.

Return a structured JSON output with the following format:
{{
  "silver_conformed_tables": [
    {{
      "source_table": "bronze_table_name",
      "subject_area": "SUBJECT_AREA_NAME",
      "target_table": "SILVER_TABLE_NAME",
      "attributes": [
        {{
          "source_column": "column_name",
          "target_attribute": "STANDARD_ATTRIBUTE_NAME",
          "description": "IBM Model Attribute description",
          "confidence_score": 0.95
        }}
      ]
    }}
  ]
}}
Return ONLY valid JSON. Do not include markdown code block syntax."""

        messages = [
            SystemMessage(content=prompt),
            HumanMessage(content=json.dumps(bronze_schema)),
        ]
        response = self.llm.invoke(messages)
        content = response.content.strip()

        if content.startswith("```"):
            lines = content.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines[-1].startswith("```"):
                lines = lines[:-1]
            content = "\n".join(lines).strip()

        try:
            res = json.loads(content)
            res["grounded_candidates"] = grounded_candidates
            return res
        except Exception as e:
            logger.error(
                f"Failed to parse Silver Model response as JSON: {e}. Raw content: {content}"
            )
            return {
                "silver_conformed_tables": [],
                "grounded_candidates": grounded_candidates,
                "error": str(e),
                "raw": content,
            }
