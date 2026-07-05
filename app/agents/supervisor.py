import os
import logging
from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from typing import List

from .infra_agent import InfraAgent
from .code_agent import CodeAgent
from .research_agent import ResearchAgent

logger = logging.getLogger("supervisor")

# System prompt that teaches the LLM how to route
ROUTING_SYSTEM_PROMPT = """You are a Supervisor Agent that routes user requests to the correct specialist agent.

Available specialists:
- INFRA: For questions about cluster health, pod status, infrastructure config, Vault, Kong, Bedrock endpoints.
- CODE: For questions about agent capabilities, tool lists, architecture, code-level explanations, sub-tasks.
- RESEARCH: For conceptual explanations, comparisons between technologies, multi-step reasoning, and general knowledge.

Respond with ONLY one of: INFRA, CODE, RESEARCH

Examples:
- "Check cluster health" → INFRA
- "What tools do you have?" → CODE
- "What is the difference between ECS and EKS?" → RESEARCH
- "Is the system healthy?" → INFRA
- "Explain LangGraph" → RESEARCH
- "List your capabilities" → CODE
"""


class SupervisorAgent:
    """
    Supervisor that routes user prompts to the correct specialist agent
    (InfraAgent, CodeAgent, ResearchAgent) and synthesizes their output.
    """

    SPECIALIST_MAP = {
        "INFRA": "infra",
        "CODE": "code",
        "RESEARCH": "research",
    }

    def __init__(self, api_key: str):
        os.environ["_AGENT_API_KEY"] = api_key

        gateway_url = os.getenv(
            "AI_GATEWAY_URL",
            "http://kong-kong-proxy.default.svc.cluster.local:80/v1"
        )

        # Shared base LLM (no tool binding — specialists bind their own tools)
        base_llm = ChatOpenAI(
            base_url=gateway_url,
            api_key=api_key,
            model="us.amazon.nova-lite-v1:0",
            temperature=0.7,
            streaming=False,
        )

        # Router LLM — low temperature for consistent routing decisions
        self.router_llm = ChatOpenAI(
            base_url=gateway_url,
            api_key=api_key,
            model="us.amazon.nova-lite-v1:0",
            temperature=0.0,
            streaming=False,
        )

        # Instantiate each specialist with the shared base LLM
        self.infra_agent = InfraAgent(base_llm)
        self.code_agent = CodeAgent(base_llm)
        self.research_agent = ResearchAgent(base_llm)

        logger.info("SupervisorAgent initialized with 3 specialists: Infra, Code, Research")

    def _route(self, user_prompt: str) -> str:
        """Uses the router LLM to classify intent and select a specialist."""
        routing_messages = [
            SystemMessage(content=ROUTING_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]
        response = self.router_llm.invoke(routing_messages)
        decision = response.content.strip().upper()

        # Normalise — handle verbose responses
        for key in self.SPECIALIST_MAP:
            if key in decision:
                logger.info(f"Supervisor routing '{user_prompt[:60]}' → {key}")
                return key

        # Default fallback
        logger.warning(f"Could not classify intent, falling back to RESEARCH. Decision: {decision!r}")
        return "RESEARCH"

    def run(self, user_prompt: str, history: List[BaseMessage] = None) -> str:
        """
        Routes the user prompt to the correct specialist agent and returns
        the synthesized text response.
        """
        messages = list(history or [])
        messages.append(HumanMessage(content=user_prompt))

        specialist_key = self._route(user_prompt)

        if specialist_key == "INFRA":
            return self.infra_agent.run(messages)
        elif specialist_key == "CODE":
            return self.code_agent.run(messages)
        else:
            return self.research_agent.run(messages)
