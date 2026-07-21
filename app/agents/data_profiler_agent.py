import json
import logging
from langchain_core.messages import SystemMessage, HumanMessage
from contracts import BronzeSchemaContract

logger = logging.getLogger("data_profiler")


class DataProfilerAgent:
    def __init__(self, llm):
        self.llm = llm

    def profile_schema(self, value_stream_json: dict, max_retries: int = 3) -> dict:
        prompt = """You are an expert Databricks Data Profiler and Data Engineer. 
Translate the provided value stream JSON properties into a physical Databricks Bronze layer delta schema specification.
Return a structured JSON output with the following format:
{
  "entity_name": "transaction",
  "columns": [
    { "name": "txn_id", "type": "STRING" },
    { "name": "amount", "type": "DECIMAL(18,2)" }
  ]
}
Return ONLY valid JSON. Do not include markdown code block syntax."""
        messages = [
            SystemMessage(content=prompt),
            HumanMessage(content=json.dumps(value_stream_json)),
        ]

        for attempt in range(1, max_retries + 1):
            try:
                response = self.llm.invoke(messages)
                content = response.content.strip()

                if content.startswith("```"):
                    lines = content.split("\n")
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].startswith("```"):
                        lines = lines[:-1]
                    content = "\n".join(lines).strip()

                parsed = json.loads(content)
                # Fallback conversion if LLM emitted bronze_tables array format
                if (
                    "bronze_tables" in parsed
                    and isinstance(parsed["bronze_tables"], list)
                    and parsed["bronze_tables"]
                ):
                    bt = parsed["bronze_tables"][0]
                    cols = bt.get("columns", [])
                    parsed = {
                        "entity_name": bt.get("table_name", "transaction").replace(
                            "bronze_", ""
                        ),
                        "columns": [
                            {"name": c.get("name"), "type": c.get("type", "STRING")}
                            for c in cols
                            if isinstance(c, dict)
                        ],
                    }

                validated = BronzeSchemaContract(**parsed)
                return validated.model_dump()
            except Exception as e:
                logger.warning(
                    f"DataProfiler repair attempt {attempt}/{max_retries} failed: {e}"
                )
                if attempt < max_retries:
                    messages.append(
                        HumanMessage(content=f"Fix JSON schema error: {str(e)}")
                    )
                else:
                    return {
                        "entity_name": "transaction",
                        "columns": [],
                        "error": str(e),
                    }
        return {"entity_name": "transaction", "columns": []}
