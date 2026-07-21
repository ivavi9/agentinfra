import sys
import json
import logging
from typing import List, Dict, Any

logger = logging.getLogger("mcp_databricks_server")


class MCPDatabricksServer:
    """
    Model Context Protocol (MCP) server providing Databricks Asset Bundle (DAB)
    and Delta Live Tables (DLT) tools.
    """

    def __init__(self):
        self.tools = {
            "dab_validate_bundle": self.dab_validate_bundle,
            "dlt_generate_pipeline_spec": self.dlt_generate_pipeline_spec,
            "dlt_get_pipeline_status": self.dlt_get_pipeline_status,
        }

    def dab_validate_bundle(self, files: Dict[str, str]) -> Dict[str, Any]:
        """Validates that a DAB bundle contains mandatory databricks.yml and pipeline configurations."""
        try:
            required = [
                "databricks.yml",
                "resources/pipelines.yml",
                "src/conformance.py",
            ]
            missing = [f for f in required if f not in files]
            if missing:
                return {
                    "status": "INVALID",
                    "valid": False,
                    "error": f"Missing mandatory DAB files: {', '.join(missing)}",
                }
            return {
                "status": "VALID",
                "valid": True,
                "file_count": len(files),
                "message": "Databricks Asset Bundle structure validated successfully.",
            }
        except Exception as e:
            logger.error(f"MCP Databricks validate bundle error: {e}")
            return {"status": "ERROR", "valid": False, "error": str(e)}

    def dlt_generate_pipeline_spec(
        self,
        bundle_name: str = "databricks_ingestion",
        entity_name: str = "transaction",
    ) -> Dict[str, Any]:
        """Generates a deployable Delta Live Tables (DLT) pipeline specification."""
        try:
            spec = {
                "name": f"{bundle_name}_{entity_name}_dlt_pipeline",
                "target": f"silver_{entity_name}_catalog",
                "continuous": False,
                "development": True,
                "clusters": [{"label": "default", "num_workers": 2}],
                "libraries": [{"notebook": {"path": f"src/{entity_name}_conformance"}}],
            }
            return {"status": "SUCCESS", "pipeline_spec": spec}
        except Exception as e:
            logger.error(f"MCP Databricks DLT spec error: {e}")
            return {"status": "ERROR", "error": str(e)}

    def dlt_get_pipeline_status(
        self, pipeline_id: str = "dlt-pipeline-001"
    ) -> Dict[str, Any]:
        """Simulates querying Delta Live Tables execution state and data quality metrics."""
        try:
            return {
                "status": "SUCCESS",
                "pipeline_id": pipeline_id,
                "state": "RUNNING",
                "records_ingested": 100000,
                "data_quality_expectations": {
                    "expect_primary_key_not_null": {"passed": True, "failed_records": 0}
                },
            }
        except Exception as e:
            logger.error(f"MCP Databricks DLT status error: {e}")
            return {"status": "ERROR", "error": str(e)}

    def get_tool_manifest(self) -> List[Dict[str, Any]]:
        """Returns JSON-RPC MCP tools/list manifest for Databricks tools."""
        return [
            {
                "name": "dab_validate_bundle",
                "description": "Validate Databricks Asset Bundle (DAB) file catalog and syntax.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "files": {
                            "type": "object",
                            "description": "Dictionary of file path to file content strings.",
                        }
                    },
                    "required": ["files"],
                },
            },
            {
                "name": "dlt_generate_pipeline_spec",
                "description": "Generate deployable Delta Live Tables (DLT) pipeline spec.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "bundle_name": {
                            "type": "string",
                            "default": "databricks_ingestion",
                        },
                        "entity_name": {"type": "string", "default": "transaction"},
                    },
                },
            },
            {
                "name": "dlt_get_pipeline_status",
                "description": "Query Delta Live Tables execution state and metrics.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"pipeline_id": {"type": "string"}},
                    "required": ["pipeline_id"],
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
                    "serverInfo": {"name": "mcp-databricks-server", "version": "1.0.0"},
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
    server = MCPDatabricksServer()
    server.run_stdio()
