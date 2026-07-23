import re
import json
import logging
from typing import Dict, Any

logger = logging.getLogger("document_parser")


class BRDDocumentParser:
    """
    Business Requirement Document (BRD) Parser. Extracts structured specifications,
    source entity names, business requirements, and field definitions from text, markdown, or JSON formats.
    """

    @classmethod
    def parse_brd_content(cls, content: str) -> Dict[str, Any]:
        """Parses raw BRD text or JSON into a structured requirement dictionary."""
        if not content:
            return {"status": "ERROR", "error": "Empty content"}

        # Check if content is already valid JSON
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                return {
                    "status": "SUCCESS",
                    "source_format": "JSON",
                    "entity_name": parsed.get("entity_name")
                    or parsed.get("entity")
                    or "transaction",
                    "requirements": parsed.get("requirements", []),
                    "columns": parsed.get("columns", []),
                    "raw_json": parsed,
                }
        except (json.JSONDecodeError, TypeError):
            pass

        # Text / Markdown parsing heuristics
        entity_name = "transaction"
        entity_match = re.search(
            r"entity(?:\s*name)?\s*[:=]\s*([a-zA-Z0-9_]+)", content, re.IGNORECASE
        )
        if entity_match:
            entity_name = entity_match.group(1).lower()

        # Extract requirements/bullet points
        requirements = []
        for line in content.split("\n"):
            line_str = line.strip()
            if (
                line_str.startswith("-")
                or line_str.startswith("*")
                or re.match(r"^\d+\.", line_str)
            ):
                requirements.append(line_str.lstrip("-*0123456789. "))

        return {
            "status": "SUCCESS",
            "source_format": "TEXT",
            "entity_name": entity_name,
            "requirement_count": len(requirements),
            "requirements": requirements,
            "raw_text": content,
        }
