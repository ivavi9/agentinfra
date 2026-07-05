import os
import json
import logging
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langgraph.prebuilt import ToolNode
from langgraph.graph import StateGraph, END
from typing import TypedDict, Annotated, List
from langgraph.graph.message import add_messages

logger = logging.getLogger("research_agent")


# ── Tools scoped to research / knowledge synthesis domain ────────────────────

@tool
def synthesize_knowledge(question: str, context: str = "") -> str:
    """Performs a focused knowledge synthesis pass on a question, optionally with
    additional context to ground the answer. Use for explanations, comparisons,
    and multi-hop reasoning tasks.

    Args:
        question: The question or concept to research and explain.
        context: Optional extra context or constraints to guide the answer.
    """
    gateway_url = os.getenv(
        "AI_GATEWAY_URL",
        "http://kong-kong-proxy.default.svc.cluster.local:80/v1"
    )
    prompt = question if not context else f"Context: {context}\n\nQuestion: {question}"
    try:
        client = ChatOpenAI(
            base_url=gateway_url,
            api_key=os.getenv("_AGENT_API_KEY", "placeholder"),
            model="us.amazon.nova-lite-v1:0",
            temperature=0.3,
        )
        result = client.invoke([HumanMessage(content=prompt)])
        return json.dumps({"answer": result.content})
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def compare_concepts(concept_a: str, concept_b: str) -> str:
    """Produces a structured comparison between two concepts, technologies,
    or architectural patterns. Returns a pros/cons and use-case breakdown.

    Args:
        concept_a: First concept to compare.
        concept_b: Second concept to compare.
    """
    gateway_url = os.getenv(
        "AI_GATEWAY_URL",
        "http://kong-kong-proxy.default.svc.cluster.local:80/v1"
    )
    prompt = (
        f"Produce a concise structured comparison between '{concept_a}' and '{concept_b}'. "
        f"Include: key differences, when to use each, and a summary recommendation."
    )
    try:
        client = ChatOpenAI(
            base_url=gateway_url,
            api_key=os.getenv("_AGENT_API_KEY", "placeholder"),
            model="us.amazon.nova-lite-v1:0",
            temperature=0.3,
        )
        result = client.invoke([HumanMessage(content=prompt)])
        return json.dumps({"comparison": result.content})
    except Exception as e:
        return json.dumps({"error": str(e)})


RESEARCH_TOOLS = [synthesize_knowledge, compare_concepts]


# ── Research Agent graph ──────────────────────────────────────────────────────

class ResearchState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]


class ResearchAgent:
    """Specialist agent: multi-hop knowledge synthesis, explanations, comparisons."""

    def __init__(self, llm_base: ChatOpenAI):
        self.llm = llm_base.bind_tools(RESEARCH_TOOLS)
        self.tool_node = ToolNode(RESEARCH_TOOLS)
        self.graph = self._build()

    def _call_model(self, state: ResearchState) -> dict:
        system_prompt = SystemMessage(
            content="You are the ResearchAgent, a specialist conceptual research and comparison subagent. "
                    "You have tools available to synthesize knowledge (synthesize_knowledge) and compare concepts (compare_concepts). "
                    "You MUST invoke the appropriate tool to run the comparison or synthesis before answering. "
                    "Always call compare_concepts if comparing two topics, or synthesize_knowledge if researching a concept."
        )
        messages = [system_prompt] + state["messages"]
        return {"messages": [self.llm.invoke(messages)]}

    def _route(self, state: ResearchState) -> str:
        last = state["messages"][-1]
        logger.info(f"Research route check: last message type={type(last)}, tool_calls={getattr(last, 'tool_calls', None)}")
        if hasattr(last, "tool_calls") and last.tool_calls:
            return "tools"
        return END

    def _build(self):
        b = StateGraph(ResearchState)
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
        return "Research agent completed with no text output."
