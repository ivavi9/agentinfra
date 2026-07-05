import os
import json
import httpx
import logging
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langgraph.prebuilt import ToolNode
from langgraph.graph import StateGraph, END
from typing import TypedDict, Annotated, List
from langgraph.graph.message import add_messages

logger = logging.getLogger("infra_agent")


# ── Tools scoped to infrastructure domain ────────────────────────────────────

@tool
def get_infrastructure_status() -> str:
    """Returns the current EKS cluster name, region, Vault address,
    Kong gateway URL, and the AI model currently serving requests."""
    status = {
        "cluster": os.getenv("CLUSTER_NAME", "agent-infra-cluster"),
        "region": os.getenv("AWS_REGION", "us-east-1"),
        "vault_addr": os.getenv("VAULT_ADDR", "http://vault.default.svc.cluster.local:8200"),
        "ai_gateway_url": os.getenv(
            "AI_GATEWAY_URL",
            "http://kong-kong-proxy.default.svc.cluster.local:80/v1"
        ),
        "model": "us.amazon.nova-lite-v1:0",
        "platform": "Amazon Bedrock via Kong AI Gateway",
        "namespace": "default",
        "pod_name": os.getenv("HOSTNAME", "unknown"),
    }
    return json.dumps(status, indent=2)


@tool
def call_health_endpoint() -> str:
    """Makes an HTTP GET request to the agent's own /health endpoint
    and returns the live pod health status from Vault and Kong."""
    try:
        response = httpx.get("http://localhost:8000/health", timeout=5.0)
        return json.dumps({"status_code": response.status_code, "body": response.json()})
    except Exception as e:
        return json.dumps({"error": str(e)})


INFRA_TOOLS = [get_infrastructure_status, call_health_endpoint]


# ── Infra Agent graph ────────────────────────────────────────────────────────

class InfraState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]


class InfraAgent:
    """Specialist agent: infrastructure status, cluster health, endpoint diagnostics."""

    def __init__(self, llm_base: ChatOpenAI):
        self.llm = llm_base.bind_tools(INFRA_TOOLS)
        self.tool_node = ToolNode(INFRA_TOOLS)
        self.graph = self._build()

    def _call_model(self, state: InfraState) -> dict:
        system_prompt = SystemMessage(
            content="You are the InfraAgent, a specialist EKS infrastructure diagnostics subagent. "
                    "You have tools available to check EKS cluster status (get_infrastructure_status) and "
                    "Kubernetes pod health (call_health_endpoint). "
                    "You MUST invoke the appropriate tool to retrieve live data before answering. "
                    "Do not guess or assume. Always invoke a tool if the user asks about the cluster status or health."
        )
        messages = [system_prompt] + state["messages"]
        return {"messages": [self.llm.invoke(messages)]}

    def _route(self, state: InfraState) -> str:
        last = state["messages"][-1]
        logger.info(f"Infra route check: last message type={type(last)}, tool_calls={getattr(last, 'tool_calls', None)}")
        if hasattr(last, "tool_calls") and last.tool_calls:
            return "tools"
        return END

    def _build(self):
        b = StateGraph(InfraState)
        b.add_node("agent", self._call_model)
        b.add_node("tools", self.tool_node)
        b.set_entry_point("agent")
        b.add_conditional_edges("agent", self._route, {"tools": "tools", END: END})
        b.add_edge("tools", "agent")
        return b.compile()

    def run(self, messages: List[BaseMessage]) -> str:
        result = self.graph.invoke({"messages": messages})
        ai_contents = []
        for msg in result["messages"]:
            if isinstance(msg, AIMessage) and msg.content:
                val = msg.content.strip()
                if val and val not in ai_contents:
                    ai_contents.append(val)
        if ai_contents:
            return "\n\n".join(ai_contents)
        return "Infra agent completed with no text output."
