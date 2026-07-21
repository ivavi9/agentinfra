import sys
import json
import logging
import boto3
from typing import List, Dict, Any

logger = logging.getLogger("mcp_s3_server")


class MCPS3Server:
    """
    Model Context Protocol (MCP) server providing AWS S3 tools.
    Encapsulates keyless EKS IRSA boto3 operations and exposes JSON-RPC 2.0 MCP interface.
    """

    def __init__(self):
        self.s3_client = boto3.client("s3")
        self.tools = {
            "s3_discover_landing_bucket": self.s3_discover_landing_bucket,
            "s3_list_raw_assets": self.s3_list_raw_assets,
            "s3_read_json_records": self.s3_read_json_records,
        }

    def s3_discover_landing_bucket(
        self, prefix: str = "agent-infra-landing-bucket-"
    ) -> Dict[str, Any]:
        """Discovers the landing bucket dynamically by listing buckets matching prefix."""
        try:
            buckets = self.s3_client.list_buckets()
            for b in buckets.get("Buckets", []):
                name = b["Name"]
                if name.startswith(prefix):
                    return {"status": "SUCCESS", "bucket": name}
            return {
                "status": "ERROR",
                "error": f"No bucket found matching prefix '{prefix}'",
            }
        except Exception as e:
            logger.error(f"MCP S3 discover error: {e}")
            return {"status": "ERROR", "error": str(e)}

    def s3_list_raw_assets(
        self, bucket: str, entity_name: str = "transaction"
    ) -> Dict[str, Any]:
        """Lists raw S3 object keys stored under raw/{entity_name}/ prefix."""
        try:
            prefix = f"raw/{entity_name}/"
            resp = self.s3_client.list_objects_v2(Bucket=bucket, Prefix=prefix)
            keys = [item["Key"] for item in resp.get("Contents", [])]
            return {"status": "SUCCESS", "bucket": bucket, "keys": keys}
        except Exception as e:
            logger.error(f"MCP S3 list raw assets error: {e}")
            return {"status": "ERROR", "error": str(e)}

    def s3_read_json_records(self, bucket: str, key: str) -> Dict[str, Any]:
        """Downloads and parses JSON Lines or JSON object from S3."""
        try:
            response = self.s3_client.get_object(Bucket=bucket, Key=key)
            content = response["Body"].read().decode("utf-8")
            records = []
            for line in content.split("\n"):
                if line.strip():
                    records.append(json.loads(line.strip()))
            return {
                "status": "SUCCESS",
                "bucket": bucket,
                "key": key,
                "record_count": len(records),
                "records": records,
            }
        except Exception as e:
            logger.error(f"MCP S3 read json records error: {e}")
            return {"status": "ERROR", "error": str(e)}

    def get_tool_manifest(self) -> List[Dict[str, Any]]:
        """Returns JSON-RPC MCP tools/list manifest."""
        return [
            {
                "name": "s3_discover_landing_bucket",
                "description": "Discover S3 landing bucket dynamically matching prefix.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "prefix": {
                            "type": "string",
                            "default": "agent-infra-landing-bucket-",
                        }
                    },
                },
            },
            {
                "name": "s3_list_raw_assets",
                "description": "List raw S3 object keys for a given business entity.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "bucket": {"type": "string"},
                        "entity_name": {"type": "string", "default": "transaction"},
                    },
                    "required": ["bucket"],
                },
            },
            {
                "name": "s3_read_json_records",
                "description": "Download and parse JSON/JSONL raw data records from S3.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "bucket": {"type": "string"},
                        "key": {"type": "string"},
                    },
                    "required": ["bucket", "key"],
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
                    "serverInfo": {"name": "mcp-s3-server", "version": "1.0.0"},
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
        """Runs stdio loop reading JSON-RPC requests from stdin and responding to stdout."""
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
    server = MCPS3Server()
    server.run_stdio()
