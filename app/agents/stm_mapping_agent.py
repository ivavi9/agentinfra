import json
import logging
from langchain_core.messages import SystemMessage, HumanMessage

logger = logging.getLogger("stm_mapping")

class STMMappingAgent:
    def __init__(self, llm):
        self.llm = llm

    def generate_mapping(self, bronze_schema: dict, silver_conformed: dict) -> dict:
        prompt = """You are an expert Data Integration Engineer. Produce a detailed Source-to-Target Mapping (STM) matrix.
For each column in the raw Bronze schema, define its mapping to the conformed target Silver attribute, including:
1. Target table and column name.
2. Spark SQL / PySpark transformation rules (e.g., direct move, string formatting, date parsing, numeric casting).
3. Primary business key surrogate generation rules (e.g. using sha2 hashing on primary keys).
4. System audit columns to inject (e.g. `_ingested_at` using `current_timestamp()`, and `_source_system`).

Return a structured JSON output with the following format:
{
  "mappings": [
    {
      "source_table": "bronze_table_name",
      "source_column": "column_name",
      "target_table": "silver_table_name",
      "target_column": "attribute_name",
      "transformation_rule": "SPARK_SQL_EXPRESSION",
      "is_surrogate_key": true/false
    }
  ]
}
Return ONLY valid JSON. Do not include markdown code block syntax."""
        input_data = {
            "bronze_schema": bronze_schema,
            "silver_conformed": silver_conformed
        }
        messages = [
            SystemMessage(content=prompt),
            HumanMessage(content=json.dumps(input_data))
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
            return json.loads(content)
        except Exception as e:
            logger.error(f"Failed to parse STM Mapping response as JSON: {e}. Raw content: {content}")
            return {"mappings": [], "error": str(e), "raw": content}
