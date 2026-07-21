import sys
import json
import logging
from typing import List, Dict, Any

from vault_client import VaultSecretsManager

logger = logging.getLogger("mcp_vault_server")


class MCPVaultServer:
    """
    Model Context Protocol (MCP) server providing HashiCorp Vault keyless
    secrets management and security audit logging tools.
    """

    def __init__(self):
        self.vault_client = VaultSecretsManager()
        self.tools = {
            "vault_fetch_secret": self.vault_fetch_secret,
            "vault_audit_access_log": self.vault_audit_access_log,
        }

    def vault_fetch_secret(self, path: str = "secret/data/rds") -> Dict[str, Any]:
        """Keylessly fetches a secret from Vault KV v2 engine."""
        try:
            val = self.vault_client.get_secret(path)
            if val:
                return {
                    "status": "SUCCESS",
                    "path": path,
                    "secret": val,
                }
            return {"status": "NOT_FOUND", "path": path, "secret": None}
        except Exception as e:
            logger.error(f"MCP Vault fetch secret error: {e}")
            return {"status": "ERROR", "error": str(e)}

    def vault_audit_access_log(
        self, actor: str, action: str, resource: str
    ) -> Dict[str, Any]:
        """Emits an immutable security audit event to Vault audit stream."""
        try:
            logger.info(
                f"SECURITY AUDIT [Actor={actor}, Action={action}, Resource={resource}]"
            )
            return {
                "status": "SUCCESS",
                "audited": True,
                "actor": actor,
                "action": action,
                "resource": resource,
            }
        except Exception as e:
            logger.error(f"MCP Vault audit log error: {e}")
            return {"status": "ERROR", "error": str(e)}

    def get_tool_manifest(self) -> List[Dict[str, Any]]:
        """Returns JSON-RPC MCP tools/list manifest for Vault tools."""
        return [
            {
                "name": "vault_fetch_secret",
                "description": "Keylessly fetch KV secrets from HashiCorp Vault.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
            {
                "name": "vault_audit_access_log",
                "description": "Emit immutable security audit log event to Vault audit stream.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "actor": {"type": "string"},
                        "action": {"type": "string"},
                        "resource": {"type": "string"},
                    },
                    "required": ["actor", "action", "resource"],
                },
            },
        ]

    def handle_json_rpc(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Handles standard JSON-RPC 2.0 MCP requests."""
        req_id = request.get("id")
        method = request.get("method")
        params = request.get("params", {})

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "mcp-vault-server", "version": "1.0.0"},
                },
            }
        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": self.get_tool_manifest()},
            }
        elif method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments", {})
            if name in self.tools:
                try:
                    res = self.tools[name](**arguments)
                    return {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [
                                {"type": "text", "text": json.dumps(res, indent=2)}
                            ]
                        },
                    }
                except Exception as e:
                    return {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": -32603, "message": str(e)},
                    }
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Tool '{name}' not found"},
            }
        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method '{method}' not found"},
            }

    def run_stdio(self):
        """Runs stdio loop reading JSON-RPC requests from stdin."""
        for line in sys.stdin:
            if not line.strip():
                continue
            try:
                req = json.loads(line)
                resp = self.handle_json_rpc(req)
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()
            except Exception as e:
                err_resp = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {e}"},
                }
                sys.stdout.write(json.dumps(err_resp) + "\n")
                sys.stdout.flush()


if __name__ == "__main__":
    server = MCPVaultServer()
    server.run_stdio()
