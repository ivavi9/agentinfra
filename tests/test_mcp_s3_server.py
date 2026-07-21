from unittest.mock import MagicMock
from langchain_core.tools import StructuredTool

try:
    from app.mcp_s3_server import MCPS3Server
    from app.mcp_client import MCPS3ClientAdapter
except ModuleNotFoundError:
    from mcp_s3_server import MCPS3Server
    from mcp_client import MCPS3ClientAdapter


def test_mcp_s3_server_manifest():
    server = MCPS3Server()
    manifest = server.get_tool_manifest()
    assert len(manifest) == 3
    tool_names = [t["name"] for t in manifest]
    assert "s3_discover_landing_bucket" in tool_names
    assert "s3_list_raw_assets" in tool_names
    assert "s3_read_json_records" in tool_names


def test_mcp_s3_server_json_rpc_handlers():
    server = MCPS3Server()

    # Test initialize method
    init_res = server.handle_json_rpc({"id": 1, "method": "initialize"})
    assert init_res["result"]["serverInfo"]["name"] == "mcp-s3-server"

    # Test tools/list method
    list_res = server.handle_json_rpc({"id": 2, "method": "tools/list"})
    tools = list_res["result"]["tools"]
    assert len(tools) == 3

    # Test mock tools/call method
    mock_s3 = MagicMock()
    mock_s3.list_buckets.return_value = {
        "Buckets": [{"Name": "agent-infra-landing-bucket-test"}]
    }
    server.s3_client = mock_s3

    call_res = server.handle_json_rpc(
        {
            "id": 3,
            "method": "tools/call",
            "params": {"name": "s3_discover_landing_bucket", "arguments": {}},
        }
    )
    assert call_res["result"]["content"][0]["type"] == "text"
    assert "agent-infra-landing-bucket-test" in call_res["result"]["content"][0]["text"]


def test_mcp_client_adapter_langchain_tools():
    adapter = MCPS3ClientAdapter()
    langchain_tools = adapter.get_langchain_tools()
    assert len(langchain_tools) == 3
    for tool in langchain_tools:
        assert isinstance(tool, StructuredTool)
