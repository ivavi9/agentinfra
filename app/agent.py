import os
import json
import logging
import httpx
from typing import TypedDict, List, Annotated
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

logger = logging.getLogger("agent-core")

# ────────────────────────────────────────────────────────────
# Tool definitions
# ────────────────────────────────────────────────────────────

@tool
def get_infrastructure_status() -> str:
    """
    Returns the current deployment state of the agent infrastructure,
    including the EKS cluster name, Vault address, Kong gateway endpoint,
    and the model currently being used.
    """
    status = {
        "cluster": os.getenv("CLUSTER_NAME", "agent-infra-cluster"),
        "region": os.getenv("AWS_REGION", "us-east-1"),
        "vault_addr": os.getenv("VAULT_ADDR", "http://vault.default.svc.cluster.local:8200"),
        "ai_gateway_url": os.getenv("AI_GATEWAY_URL", "http://kong-kong-proxy.default.svc.cluster.local:80/v1"),
        "model": "us.amazon.nova-lite-v1:0",
        "platform": "Amazon Bedrock (via Kong AI Gateway)",
        "namespace": "default",
        "pod_name": os.getenv("HOSTNAME", "unknown"),
    }
    return json.dumps(status, indent=2)


@tool
def get_agent_capabilities() -> str:
    """
    Returns a list of capabilities and registered tools available to this agent.
    Use this to help the user understand what the agent can and cannot do.
    """
    capabilities = {
        "agent_type": "LangGraph Stateful Agent",
        "framework": "LangGraph + LangChain",
        "backend_model": "Amazon Bedrock Nova Lite (us.amazon.nova-lite-v1:0)",
        "gateway": "Kong AI Gateway (ai-proxy plugin, OpenAI-compatible)",
        "secrets": "HashiCorp Vault (Kubernetes OIDC ServiceAccount auth)",
        "registered_tools": [
            {
                "name": "get_infrastructure_status",
                "description": "Returns live EKS cluster, Vault, and Kong endpoint configuration."
            },
            {
                "name": "get_agent_capabilities",
                "description": "Returns this list of capabilities and tools."
            },
            {
                "name": "call_health_endpoint",
                "description": "Makes an HTTP GET call to /health and returns current pod health."
            },
            {
                "name": "run_sub_prompt",
                "description": "Recursively dispatches an internal sub-prompt to the LLM reasoning chain."
            }
        ]
    }
    return json.dumps(capabilities, indent=2)


@tool
def call_health_endpoint() -> str:
    """
    Makes an HTTP GET request to the agent's own /health endpoint and returns the response.
    Use this to verify the agent is connected to Vault and the system is healthy.
    """
    try:
        response = httpx.get("http://localhost:8000/health", timeout=5.0)
        return json.dumps({
            "status_code": response.status_code,
            "body": response.json()
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def run_sub_prompt(sub_prompt: str) -> str:
    """
    Dispatches an internal sub-prompt to this agent's LLM and returns the model's
    text response. Use this to break down complex multi-step reasoning tasks.
    
    Args:
        sub_prompt: The specific question or task to dispatch to the reasoning model.
    """
    try:
        gateway_url = os.getenv("AI_GATEWAY_URL", "http://kong-kong-proxy.default.svc.cluster.local:80/v1")
        api_key = os.getenv("_AGENT_API_KEY", "placeholder")
        
        client = ChatOpenAI(
            base_url=gateway_url,
            api_key=api_key,
            model="us.amazon.nova-lite-v1:0",
            temperature=0.5,
            streaming=False
        )
        result = client.invoke([HumanMessage(content=sub_prompt)])
        return result.content
    except Exception as e:
        return f"Sub-prompt execution failed: {str(e)}"


# ────────────────────────────────────────────────────────────
# Agent State & Graph
# ────────────────────────────────────────────────────────────

TOOLS = [get_infrastructure_status, get_agent_capabilities, call_health_endpoint, run_sub_prompt]

class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]


class LangGraphAgent:
    def __init__(self, api_key: str):
        # Store key for sub-prompt tool access
        os.environ["_AGENT_API_KEY"] = api_key

        gateway_url = os.getenv("AI_GATEWAY_URL", "http://kong-kong-proxy.default.svc.cluster.local:80/v1")

        # Bind tools to LLM for function calling
        base_llm = ChatOpenAI(
            base_url=gateway_url,
            api_key=api_key,
            model="us.amazon.nova-lite-v1:0",
            temperature=0.7,
            streaming=False
        )
        self.llm = base_llm.bind_tools(TOOLS)
        self.tool_node = ToolNode(TOOLS)
        self.workflow = self._build_graph()

    def _agent_node(self, state: AgentState) -> dict:
        """Invokes LLM with tool bindings via unified AI Gateway proxy."""
        response = self.llm.invoke(state["messages"])
        return {"messages": [response]}

    def _should_use_tool(self, state: AgentState) -> str:
        """Conditional router: continue to tool executor or finish."""
        last = state["messages"][-1]
        if hasattr(last, "tool_calls") and last.tool_calls:
            return "tools"
        return END

    def _build_graph(self):
        """Compiles the state machine graph with tool-calling loop."""
        builder = StateGraph(AgentState)

        builder.add_node("agent", self._agent_node)
        builder.add_node("tools", self.tool_node)

        builder.set_entry_point("agent")

        # Conditional: if model returns a tool call → run tool, else finish
        builder.add_conditional_edges("agent", self._should_use_tool, {
            "tools": "tools",
            END: END
        })

        # After tool execution, feed results back to agent for synthesis
        builder.add_edge("tools", "agent")

        return builder.compile()

    def run(self, user_prompt: str, history: List[BaseMessage] = None) -> str:
        """Executes the agent state graph with tool-calling loop and returns the final text response."""
        messages = list(history or [])
        messages.append(HumanMessage(content=user_prompt))

        result = self.workflow.invoke({"messages": messages})

        # Extract the last AI message (after tool synthesis)
        for msg in reversed(result["messages"]):
            if isinstance(msg, AIMessage) and msg.content:
                return msg.content

        return "Agent completed reasoning without generating a final response."
