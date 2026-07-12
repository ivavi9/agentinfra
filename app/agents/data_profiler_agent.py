import json
import logging
from langchain_core.messages import SystemMessage, HumanMessage

logger = logging.getLogger("data_profiler")

class DataProfilerAgent:
    def __init__(self, llm):
        self.llm = llm

    def profile_schema(self, value_stream_json: dict) -> dict:
        prompt = """You are an expert Databricks Data Profiler and Data Engineer. 
Translate the provided value stream JSON properties into a physical Databricks Bronze layer delta schema specification.
For each entity, define:
1. Target table name inside Bronze layer (prefixed with 'bronze_').
2. Database column mappings, choosing optimal Spark SQL types (STRING, BIGINT, INT, DOUBLE, TIMESTAMP, DECIMAL, etc.).
3. Nullability rules, identifying primary keys and partitions.
4. Data quality expectations (e.g. checks that columns are not null or format values match).

Return a structured JSON output with the following format:
{
  "bronze_tables": [
    {
      "table_name": "bronze_table_name",
      "columns": [
        { "name": "column_name", "type": "SPARK_SQL_TYPE", "nullable": true/false }
      ],
      "primary_key": "column_name",
      "partition_columns": ["column_name"],
      "file_format": "delta",
      "data_quality_expectations": {
        "expect_column_values_to_not_be_null": ["column_name"]
      }
    }
  ]
}
Return ONLY valid JSON. Do not include markdown code block syntax."""
        messages = [
            SystemMessage(content=prompt),
            HumanMessage(content=json.dumps(value_stream_json))
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
            logger.error(f"Failed to parse Data Profiler response as JSON: {e}. Raw content: {content}")
            return {"bronze_tables": [], "error": str(e), "raw": content}
