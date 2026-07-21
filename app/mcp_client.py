import json
import logging
from typing import List, Dict, Any, Optional
from langchain_core.tools import StructuredTool

from mcp_s3_server import MCPS3Server

logger = logging.getLogger("mcp_client")


class MCPS3ClientAdapter:
    """
    MCP Client Adapter that connects to MCPS3Server and converts MCP S3 tools
    into LangChain / LangGraph compatible StructuredTool objects.
    """

    def __init__(self, mcp_server: Optional[MCPS3Server] = None):
        self.server = mcp_server or MCPS3Server()

    def discover_landing_bucket(
        self, prefix: str = "agent-infra-landing-bucket-"
    ) -> str:
        """Call MCP s3_discover_landing_bucket tool."""
        res = self.server.s3_discover_landing_bucket(prefix=prefix)
        if res.get("status") == "SUCCESS":
            return res.get("bucket", "")
        raise FileNotFoundError(res.get("error", "Landing bucket discovery failed"))

    def list_raw_assets(
        self, bucket: str, entity_name: str = "transaction"
    ) -> List[str]:
        """Call MCP s3_list_raw_assets tool."""
        res = self.server.s3_list_raw_assets(bucket=bucket, entity_name=entity_name)
        if res.get("status") == "SUCCESS":
            return res.get("keys", [])
        return []

    def read_json_records(self, bucket: str, key: str) -> List[Dict[str, Any]]:
        """Call MCP s3_read_json_records tool."""
        res = self.server.s3_read_json_records(bucket=bucket, key=key)
        if res.get("status") == "SUCCESS":
            return res.get("records", [])
        raise RuntimeError(f"Failed to read S3 asset via MCP: {res.get('error')}")

    def get_langchain_tools(self) -> List[StructuredTool]:
        """Converts MCP server tool manifest into LangChain StructuredTools."""
        manifest = self.server.get_tool_manifest()
        langchain_tools = []

        for t in manifest:
            name = t["name"]
            desc = t["description"]
            func = self.server.tools.get(name)
            if func:

                def _make_tool_wrapper(fn):
                    def _wrapper(**kwargs):
                        res = fn(**kwargs)
                        return json.dumps(res, indent=2)

                    return _wrapper

                st = StructuredTool.from_function(
                    func=_make_tool_wrapper(func),
                    name=name,
                    description=desc,
                )
                langchain_tools.append(st)

        return langchain_tools
