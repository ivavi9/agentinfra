import json
import logging
from langchain_core.messages import SystemMessage, HumanMessage
from contracts import ValueStreamContract

logger = logging.getLogger("ba_analyst")


class BAAnalystAgent:
    def __init__(self, llm):
        self.llm = llm

    def analyze_brd(self, brd_text: str, max_retries: int = 3) -> dict:
        prompt = """You are an expert Business Analyst. Parse the provided Business Requirement Document (BRD) detailing a business value stream.
Extract all key business entities, their key attributes, expected event volume, transaction frequency, SLA characteristics, and target source system fields.
Return a structured JSON output with the following format:
{
  "domain": "Retail Banking",
  "entity_name": "transaction",
  "business_keys": ["txn_id"]
}
Return ONLY valid JSON. Do not include markdown code block syntax (like ```json)."""
        messages = [SystemMessage(content=prompt), HumanMessage(content=brd_text)]

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
                # Fallback structure if LLM outputs value_streams format
                if (
                    "value_streams" in parsed
                    and isinstance(parsed["value_streams"], list)
                    and parsed["value_streams"]
                ):
                    vs = parsed["value_streams"][0]
                    entity = vs.get("entities", [{}])[0].get("name", "transaction")
                    pk = vs.get("entities", [{}])[0].get("primary_key", "id")
                    parsed = {
                        "domain": vs.get("name", "Finance"),
                        "entity_name": entity,
                        "business_keys": [pk],
                    }
                validated = ValueStreamContract(**parsed)
                return validated.model_dump()
            except Exception as e:
                logger.warning(
                    f"BAAnalyst repair attempt {attempt}/{max_retries} failed: {e}"
                )
                if attempt < max_retries:
                    messages.append(
                        HumanMessage(content=f"Fix JSON formatting error: {str(e)}")
                    )
                else:
                    return {
                        "domain": "General",
                        "entity_name": "transaction",
                        "business_keys": ["id"],
                        "error": str(e),
                    }
        return {
            "domain": "General",
            "entity_name": "transaction",
            "business_keys": ["id"],
        }
