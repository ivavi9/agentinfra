import json


def extract_json_payload(response_text: str) -> dict:
    """Helper mimicking agent response JSON extraction."""
    text = response_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def test_extract_json_with_fenced_markdown():
    raw = '```json\n{"mappings": [{"source": "id", "target": "txn_id"}]}\n```'
    result = extract_json_payload(raw)
    assert "mappings" in result
    assert result["mappings"][0]["source"] == "id"


def test_extract_json_raw_string():
    raw = '{"status": "ok", "count": 5}'
    result = extract_json_payload(raw)
    assert result["status"] == "ok"
    assert result["count"] == 5


def test_extract_json_malformed_fallback():
    raw = "This is plain text response without JSON."
    result = extract_json_payload(raw)
    assert result == {}
