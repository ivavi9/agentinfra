import json
import logging
from langchain_core.messages import SystemMessage, HumanMessage
from contracts import MappingMatrixContract

logger = logging.getLogger("stm_mapping")


class STMMappingAgent:
    def __init__(self, llm):
        self.llm = llm

    def generate_mapping(
        self, bronze_schema: dict, silver_conformed: dict, max_retries: int = 3
    ) -> dict:
        base_prompt = """You are an expert Data Integration Engineer. Produce a detailed Source-to-Target Mapping (STM) matrix.
For each column in the raw Bronze schema, define its mapping to the conformed target Silver attribute, including:
1. Target table and column name.
2. Transformation rules matching one of the supported Transform DSL types: DIRECT, CAST, SHA256, TO_TIMESTAMP, LITERAL, TRIM, DEFAULT.
3. Primary business key surrogate generation rules (e.g. using SHA256 on primary keys).

Return a structured JSON output matching this schema:
{
  "mappings": [
    {
      "source_table": "bronze_table_name",
      "source_column": "column_name",
      "target_table": "silver_table_name",
      "target_column": "attribute_name",
      "transformation_rule": "CAST(amount AS DECIMAL(18,2))",
      "transform_dsl": "CAST",
      "is_surrogate_key": false
    }
  ]
}
Return ONLY valid JSON. Do not include markdown code block syntax."""

        input_data = {
            "bronze_schema": bronze_schema,
            "silver_conformed": silver_conformed,
        }

        messages = [
            SystemMessage(content=base_prompt),
            HumanMessage(content=json.dumps(input_data)),
        ]

        # Repair loop with up to max_retries attempts
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
                # Validate against Pydantic contract
                validated = MappingMatrixContract(**parsed)
                logger.info(
                    f"Successfully validated mapping matrix on attempt {attempt}"
                )
                return validated.model_dump()
            except Exception as e:
                logger.warning(
                    f"Repair loop attempt {attempt}/{max_retries} failed validation: {e}"
                )
                if attempt < max_retries:
                    # Append feedback message asking the model to fix its formatting/schema
                    repair_instruction = f"Your previous response failed Pydantic validation: {str(e)}. Please fix the JSON output."
                    messages.append(HumanMessage(content=repair_instruction))
                else:
                    logger.error(f"Repair loop exhausted after {max_retries} attempts.")
                    return {
                        "mappings": [],
                        "error": f"Contract validation failed: {str(e)}",
                    }
        return {"mappings": [], "error": "Repair loop failed"}
