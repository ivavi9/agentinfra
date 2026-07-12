import json
import logging
from langchain_core.messages import SystemMessage, HumanMessage

logger = logging.getLogger("silver_model")

class SilverModelAgent:
    def __init__(self, llm):
        self.llm = llm

    def conform_model(self, bronze_schema: dict) -> dict:
        prompt = """You are an expert Enterprise Data Architect specializing in the IBM Banking Data Warehouse (BDW) and Industry Models.
Conform the provided Databricks Bronze layer schemas to standard IBM BDW structures.
Classify each Bronze table into:
1. IBM Subject Area (e.g., INVOLVED_PARTY, FINANCIAL_INSTRUMENT, ARRANGEMENT, LOCATION, CHANNEL, EVENT).
2. Target Silver Table (e.g., INDIVIDUAL, ORGANISATION, DEPOSIT_ACCOUNT, CUSTOMER_TRANSACTION, FINANCIAL_TRANSACTION).
3. Standard Target Attributes matching the raw columns (e.g., TXN_ID -> AC_TXN_ID, AMT -> AC_TXN_VAL_AM, CUST_ID -> IP_ID).

Return a structured JSON output with the following format:
{
  "silver_conformed_tables": [
    {
      "source_table": "bronze_table_name",
      "subject_area": "SUBJECT_AREA_NAME",
      "target_table": "SILVER_TABLE_NAME",
      "attributes": [
        { "source_column": "column_name", "target_attribute": "STANDARD_ATTRIBUTE_NAME", "description": "IBM Model Attribute description" }
      ]
    }
  ]
}
Return ONLY valid JSON. Do not include markdown code block syntax."""
        messages = [
            SystemMessage(content=prompt),
            HumanMessage(content=json.dumps(bronze_schema))
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
            logger.error(f"Failed to parse Silver Model response as JSON: {e}. Raw content: {content}")
            return {"silver_conformed_tables": [], "error": str(e), "raw": content}
