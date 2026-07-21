import json
import logging
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException, Header

from mcp_s3_server import MCPS3Server
from mcp_postgres_server import MCPPostgresServer
from mcp_databricks_server import MCPDatabricksServer
from mcp_vault_server import MCPVaultServer

logger = logging.getLogger("mcp_gateway")

app = FastAPI(
    title="MCP Gateway Control Plane",
    description="Unified Router, RBAC Enforcer, and Tool Aggregator for MCP Tool Servers",
    version="1.0.0",
)


class MCPGatewayControlPlane:
    """
    Central control plane aggregating backend MCP servers, enforcing tool RBAC,
    and routing JSON-RPC tool invocations.
    """

    def __init__(self):
        self.servers: Dict[str, Any] = {
            "s3": MCPS3Server(),
            "postgres": MCPPostgresServer(),
            "databricks": MCPDatabricksServer(),
            "vault": MCPVaultServer(),
        }

        # Tool-to-server routing lookup
        self.tool_routing: Dict[str, Any] = {}
        self.refresh_registry()

    def refresh_registry(self):
        self.tool_routing.clear()
        for server in self.servers.values():
            for t in server.get_tool_manifest():
                self.tool_routing[t["name"]] = server

    def get_aggregated_manifest(
        self, role: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Returns merged tool manifest, optionally filtered by caller RBAC role."""
        aggregated = []
        for server in self.servers.values():
            for t in server.get_tool_manifest():
                tool_name = t["name"]
                if self._check_rbac_permission(role, tool_name):
                    aggregated.append(t)
        return aggregated

    def _check_rbac_permission(self, role: Optional[str], tool_name: str) -> bool:
        """Enforces tool-level RBAC access policies."""
        if not role or role == "admin":
            return True
        if role == "analyst":
            # Analysts can only inspect schemas and list assets
            return tool_name.startswith("s3_") or tool_name == "postgres_inspect_schema"
        if role == "developer":
            # Developers can access S3, Postgres, and Databricks DAB tools, but not Vault secrets
            return not tool_name.startswith("vault_")
        return True

    def route_tool_call(
        self, tool_name: str, arguments: Dict[str, Any], role: Optional[str] = None
    ) -> Dict[str, Any]:
        """Routes a tool call execution to the target MCP server with RBAC check."""
        if not self._check_rbac_permission(role, tool_name):
            raise HTTPException(
                status_code=403,
                detail=f"Role '{role}' is not authorized to call tool '{tool_name}'",
            )

        server = self.tool_routing.get(tool_name)
        if not server:
            raise HTTPException(
                status_code=404, detail=f"Tool '{tool_name}' not found in MCP registry"
            )

        rpc_req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }

        res = server.handle_json_rpc(rpc_req)
        if "error" in res:
            raise HTTPException(
                status_code=500, detail=f"MCP server error: {res['error']['message']}"
            )

        content = res.get("result", {}).get("content", [])
        if content and content[0].get("type") == "text":
            return json.loads(content[0]["text"])
        return res.get("result", {})


gateway = MCPGatewayControlPlane()


@app.get("/mcp/v1/tools")
def get_tools(x_mcp_role: Optional[str] = Header(None)):
    """Returns aggregated MCP tools manifest across all registered servers."""
    return {"status": "SUCCESS", "tools": gateway.get_aggregated_manifest(x_mcp_role)}


@app.post("/mcp/v1/call")
def call_tool(payload: Dict[str, Any], x_mcp_role: Optional[str] = Header(None)):
    """Proxies a tool invocation to the appropriate backend MCP server."""
    name = payload.get("name")
    arguments = payload.get("arguments", {})
    if not name:
        raise HTTPException(status_code=400, detail="Missing required field 'name'")

    result = gateway.route_tool_call(name, arguments, role=x_mcp_role)
    return {"status": "SUCCESS", "tool": name, "result": result}


@app.get("/mcp/v1/health")
def health_check():
    """Returns health status and registered tool counts for all MCP servers."""
    servers_health = {}
    total_tools = 0
    for s_name, server in gateway.servers.items():
        count = len(server.get_tool_manifest())
        total_tools += count
        servers_health[s_name] = {"status": "HEALTHY", "tool_count": count}

    return {
        "status": "HEALTHY",
        "total_tools": total_tools,
        "servers": servers_health,
    }
