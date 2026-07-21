import os
import json
import logging
from pydantic import SecretStr
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import ToolNode
from langgraph.graph import StateGraph, END
from typing import TypedDict, Annotated, List, Optional, Any
from langgraph.graph.message import add_messages

logger = logging.getLogger("code_agent")


# ── Tools scoped to code / capability domain ─────────────────────────────────


@tool
def get_agent_capabilities(query: str = "") -> str:
    """Returns a structured manifest of this agent's architecture,
    registered specialist agents, and their tool sets.

    Args:
        query: Optional filter query.
    """
    capabilities = {
        "architecture": "LangGraph Multi-Agent Supervisor",
        "specialists": [
            {
                "name": "InfraAgent",
                "role": "Cluster health, EKS/Vault/Kong status diagnostics",
                "tools": ["get_infrastructure_status", "call_health_endpoint"],
            },
            {
                "name": "CodeAgent",
                "role": "Capability discovery, code-level reasoning, sub-prompt dispatch",
                "tools": ["get_agent_capabilities", "run_sub_prompt"],
            },
            {
                "name": "ResearchAgent",
                "role": "Multi-hop knowledge synthesis, explanations, comparisons",
                "tools": ["run_sub_prompt"],
            },
        ],
        "gateway": "Kong AI Gateway (ai-proxy plugin, OpenAI-compatible)",
        "model": "us.amazon.nova-lite-v1:0 via Amazon Bedrock",
        "secrets": "HashiCorp Vault (Kubernetes OIDC ServiceAccount auth, keyless)",
    }
    return json.dumps(capabilities, indent=2)


@tool
def generate_code_snippet(prompt: str) -> str:
    """Dispatches a focused sub-question to the LLM reasoning model and returns
    the response. Use this to break complex tasks into focused reasoning steps.

    Args:
        prompt: The specific focused question or reasoning task to dispatch.
    """
    from langchain_openai import ChatOpenAI

    try:
        gateway_url = os.getenv(
            "AI_GATEWAY_URL", "http://kong-kong-proxy.default.svc.cluster.local:80/v1"
        )
        client = ChatOpenAI(
            base_url=gateway_url,
            api_key=SecretStr(os.getenv("_AGENT_API_KEY") or "placeholder"),
            model="us.amazon.nova-lite-v1:0",
            temperature=0.5,
        )
        result = client.invoke([HumanMessage(content=prompt)])
        return json.dumps({"result": result.content})
    except Exception as e:
        return json.dumps({"error": str(e)})


CODE_TOOLS = [get_agent_capabilities, generate_code_snippet]


# ── Code Agent graph ─────────────────────────────────────────────────────────


class CodeState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]


class CodeAgent:
    """Specialist agent: Python/SQL codegen, architecture queries, code synthesis."""

    def __init__(self, llm_base: ChatOpenAI):
        self.llm = llm_base.bind_tools(CODE_TOOLS)
        self.tool_node = ToolNode(CODE_TOOLS)
        self.graph = self._build()

    async def _call_model(self, state: CodeState, config: RunnableConfig) -> dict:
        system_prompt = SystemMessage(
            content="You are the CodeAgent, a specialist code generation and software architecture subagent. "
            "You have tools available to report agent capabilities (get_agent_capabilities) and generate code snippets (generate_code_snippet). "
            "You MUST invoke the appropriate tool to generate code or report capabilities before answering."
        )
        messages = [system_prompt] + state["messages"]
        for idx, msg in enumerate(messages):
            logger.info(
                f"Code msg {idx}: type={type(msg)}, content={msg.content[:100]!r}, tool_calls={getattr(msg, 'tool_calls', None)}"
            )
        response: Any = None
        async for chunk in self.llm.astream(messages, config=config):
            if response is None:
                response = chunk
            else:
                response += chunk
        return {"messages": [response]}

    def _route(self, state: CodeState) -> str:
        last = state["messages"][-1]
        logger.info(
            f"Code route check: last message type={type(last)}, tool_calls={getattr(last, 'tool_calls', None)}"
        )
        if hasattr(last, "tool_calls") and last.tool_calls:
            return "tools"
        return END

    def _build(self):
        b = StateGraph(CodeState)
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
            if (
                isinstance(msg, AIMessage)
                and isinstance(msg.content, str)
                and msg.content
            ):
                val = msg.content.strip()
                if val and val not in ai_contents:
                    ai_contents.append(val)
        if ai_contents:
            return "\n\n".join(ai_contents)
        return "Code agent completed with no text output."

    async def arun(
        self, messages: List[BaseMessage], config: Optional[RunnableConfig] = None
    ) -> str:
        result = await self.graph.ainvoke({"messages": messages}, config=config)
        ai_contents = []
        for msg in result["messages"]:
            if (
                isinstance(msg, AIMessage)
                and isinstance(msg.content, str)
                and msg.content
            ):
                val = msg.content.strip()
                if val and val not in ai_contents:
                    ai_contents.append(val)
        if ai_contents:
            return "\n\n".join(ai_contents)
        return "Code agent completed with no text output."
