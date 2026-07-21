from unittest.mock import MagicMock

try:
    from app.mcp_postgres_server import MCPPostgresServer
    from app.mcp_databricks_server import MCPDatabricksServer
    from app.mcp_vault_server import MCPVaultServer
except ModuleNotFoundError:
    from mcp_postgres_server import MCPPostgresServer
    from mcp_databricks_server import MCPDatabricksServer
    from mcp_vault_server import MCPVaultServer


def test_mcp_postgres_server():
    server = MCPPostgresServer()
    manifest = server.get_tool_manifest()
    assert len(manifest) == 3
    tool_names = [t["name"] for t in manifest]
    assert "postgres_inspect_schema" in tool_names
    assert "postgres_execute_conformance" in tool_names
    assert "postgres_get_quarantine_stats" in tool_names

    # Test initialize and tools/list JSON-RPC
    init_res = server.handle_json_rpc({"id": 1, "method": "initialize"})
    assert init_res["result"]["serverInfo"]["name"] == "mcp-postgres-server"

    list_res = server.handle_json_rpc({"id": 2, "method": "tools/list"})
    assert len(list_res["result"]["tools"]) == 3


def test_mcp_databricks_server():
    server = MCPDatabricksServer()
    manifest = server.get_tool_manifest()
    assert len(manifest) == 3

    # Test dab_validate_bundle
    valid_res = server.dab_validate_bundle(
        {
            "databricks.yml": "bundle: name",
            "resources/pipelines.yml": "pipeline:",
            "src/conformance.py": "import pyspark",
        }
    )
    assert valid_res["valid"] is True

    invalid_res = server.dab_validate_bundle({})
    assert invalid_res["valid"] is False


def test_mcp_vault_server():
    server = MCPVaultServer()
    manifest = server.get_tool_manifest()
    assert len(manifest) == 2

    # Mock vault fetch
    server.vault_client = MagicMock()
    server.vault_client.get_secret.return_value = {"db_password": "testpassword"}

    res = server.vault_fetch_secret("secret/data/rds")
    assert res["status"] == "SUCCESS"
    assert res["secret"]["db_password"] == "testpassword"
