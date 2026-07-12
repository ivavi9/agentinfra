import json
import logging
from langchain_core.messages import SystemMessage, HumanMessage

logger = logging.getLogger("ba_analyst")

class BAAnalystAgent:
    def __init__(self, llm):
        self.llm = llm

    def analyze_brd(self, brd_text: str) -> dict:
        prompt = """You are an expert Business Analyst. Parse the provided Business Requirement Document (BRD) detailing a business value stream.
Extract all key business entities, their key attributes, expected event volume, transaction frequency, SLA characteristics, and target source system fields.
Return a structured JSON output with the following format:
{
  "value_streams": [
    {
      "name": "Value Stream Name",
      "entities": [
        {
          "name": "Entity Name",
          "attributes": ["attribute1", "attribute2"],
          "primary_key": "attribute1"
        }
      ],
      "estimated_volume_per_day": 100000,
      "sla_latency": "hourly/daily/realtime",
      "source_system": "Source System name"
    }
  ]
}
Return ONLY valid JSON. Do not include markdown code block syntax (like ```json)."""
        messages = [
            SystemMessage(content=prompt),
            HumanMessage(content=brd_text)
        ]
        response = self.llm.invoke(messages)
        content = response.content.strip()
        
        # Clean potential markdown fences
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
            logger.error(f"Failed to parse BA Analyst response as JSON: {e}. Raw content: {content}")
            return {"value_streams": [], "error": str(e), "raw": content}
