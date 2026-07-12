import json
import logging
from langchain_core.messages import SystemMessage, HumanMessage

logger = logging.getLogger("dab_generator")

class DABGeneratorAgent:
    def __init__(self, llm):
        self.llm = llm

    def generate_bundle(self, mapping_matrix: list) -> dict:
        prompt = """You are an expert Databricks Platform Architect. 
Given the approved Source-to-Target Mapping (STM) matrix, generate the code for a complete deployable Databricks Asset Bundle (DAB).
Produce the following file contents as a structured JSON catalog:
1. `databricks.yml` - Defines bundle name, deployment target workspaces, and pipelines.
2. `resources/pipelines.yml` - Configures Delta Live Tables (DLT) settings and cluster constraints.
3. `src/conformance.py` - Contains the PySpark code applying the mapping rules, castings, hashes, and writing conformed Delta tables.

Return a structured JSON output with the following format:
{
  "bundle_name": "databricks_ingestion_bundle",
  "files": {
    "databricks.yml": "FILE_CONTENT_STRING",
    "resources/pipelines.yml": "FILE_CONTENT_STRING",
    "src/conformance.py": "FILE_CONTENT_STRING"
  }
}
Return ONLY valid JSON. Do not include markdown code block syntax."""
        messages = [
            SystemMessage(content=prompt),
            HumanMessage(content=json.dumps(mapping_matrix))
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
            logger.error(f"Failed to parse DAB Generator response as JSON: {e}. Raw content: {content}")
            return {"bundle_name": "default", "files": {}, "error": str(e), "raw": content}
