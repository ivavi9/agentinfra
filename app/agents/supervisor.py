import os
import logging
from typing import TypedDict, Annotated, List, Optional
from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg_pool import ConnectionPool
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

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


class SupervisorState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    specialist: Optional[str] = None


class SupervisorAgent:
    """
    Supervisor compiled as a LangGraph state graph.
    Routes user prompts to the correct specialist agent
    (InfraAgent, CodeAgent, ResearchAgent) and synthesizes their output statefully.
    """

    SPECIALIST_MAP = {
        "INFRA": "infra",
        "CODE": "code",
        "RESEARCH": "research",
    }

    def __init__(self, api_key: str, db_config: Optional[dict] = None):
        os.environ["_AGENT_API_KEY"] = api_key

        gateway_url = os.getenv(
            "AI_GATEWAY_URL",
            "http://kong-kong-proxy.default.svc.cluster.local:80/v1"
        )

        # Enable streaming support for the base LLM
        base_llm = ChatOpenAI(
            base_url=gateway_url,
            api_key=api_key,
            model="us.amazon.nova-lite-v1:0",
            temperature=0.7,
            streaming=True,
        )

        # Router LLM — low temperature, sync classification
        self.router_llm = ChatOpenAI(
            base_url=gateway_url,
            api_key=api_key,
            model="us.amazon.nova-lite-v1:0",
            temperature=0.0,
            streaming=False,
        )

        # Instantiate each specialist
        self.infra_agent = InfraAgent(base_llm)
        self.code_agent = CodeAgent(base_llm)
        self.research_agent = ResearchAgent(base_llm)

        # Build supervisor state graph
        builder = StateGraph(SupervisorState)
        
        # Add routing and specialist execution nodes
        builder.add_node("route", self._route_node)
        builder.add_node("infra", self._infra_node)
        builder.add_node("code", self._code_node)
        builder.add_node("research", self._research_node)
        
        builder.set_entry_point("route")
        
        # Add conditional edges out of route node
        builder.add_conditional_edges(
          "route",
          self._route_decision,
          {
              "INFRA": "infra",
              "CODE": "code",
              "RESEARCH": "research",
          }
        )
        
        # Connect specialists to the end point
        builder.add_edge("infra", END)
        builder.add_edge("code", END)
        builder.add_edge("research", END)
        
        # Configure RDS PostgreSQL checkpointer with in-memory fallback
        if db_config and db_config.get("db_host"):
            try:
                db_url = f"postgresql://{db_config['db_user']}:{db_config['db_password']}@{db_config['db_host']}:{db_config['db_port']}/{db_config['db_name']}"
                logger.info(f"Connecting to Postgres checkpointer: host={db_config['db_host']}, user={db_config['db_user']}")
                self.pool = ConnectionPool(conninfo=db_url, max_size=10, open=True)
                self.memory = PostgresSaver(self.pool)
                self.memory.setup()
                logger.info("SupervisorAgent successfully compiled with PostgresSaver checkpointer")
            except Exception as e:
                logger.error(f"Failed to initialize PostgresSaver checkpointer: {e}. Falling back to MemorySaver.")
                self.memory = MemorySaver()
        else:
            logger.info("Initializing SupervisorAgent with local MemorySaver checkpointer")
            self.memory = MemorySaver()

        # Set human-in-the-loop interrupts before EKS infrastructure specialist runs
        self.graph = builder.compile(checkpointer=self.memory, interrupt_before=["infra"])

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
                try:
                    from metrics import increment_route
                    increment_route(key)
                except ImportError:
                    pass
                return key

        # Default fallback
        logger.warning(f"Could not classify intent, falling back to RESEARCH. Decision: {decision!r}")
        try:
            from metrics import increment_route
            increment_route("RESEARCH")
        except ImportError:
            pass
        return "RESEARCH"

    def _route_node(self, state: SupervisorState) -> dict:
        # Find the last human message in history to classify intent
        user_prompt = ""
        for msg in reversed(state["messages"]):
            if isinstance(msg, HumanMessage) or (hasattr(msg, "role") and msg.role == "user"):
                user_prompt = msg.content
                break
        
        if not user_prompt:
            user_prompt = "explain capabilities"
            
        specialist_key = self._route(user_prompt)
        return {"specialist": specialist_key}

    def _route_decision(self, state: SupervisorState) -> str:
        return state["specialist"] or "RESEARCH"

    async def _infra_node(self, state: SupervisorState, config: RunnableConfig) -> dict:
        response = await self.infra_agent.arun(state["messages"], config)
        return {"messages": [AIMessage(content=response)]}

    async def _code_node(self, state: SupervisorState, config: RunnableConfig) -> dict:
        response = await self.code_agent.arun(state["messages"], config)
        return {"messages": [AIMessage(content=response)]}

    async def _research_node(self, state: SupervisorState, config: RunnableConfig) -> dict:
        response = await self.research_agent.arun(state["messages"], config)
        return {"messages": [AIMessage(content=response)]}

    def run(self, user_prompt: Optional[str], session_id: str = "default") -> tuple:
        """
        Runs the state graph synchronously for compatibility.
        """
        config = {"configurable": {"thread_id": session_id}}
        input_data = {"messages": [HumanMessage(content=user_prompt)]} if user_prompt is not None else None
        result = self.graph.invoke(
            input_data,
            config=config
        )
        last_msg = result["messages"][-1]
        return last_msg.content, result.get("specialist", "RESEARCH")

    async def astream(self, user_prompt: Optional[str], session_id: str = "default"):
        """
        Asynchronously streams LLM token events and specialist routing choices.
        """
        config = {"configurable": {"thread_id": session_id}}
        input_data = {"messages": [HumanMessage(content=user_prompt)]} if user_prompt is not None else None
        
        async for event in self.graph.astream_events(
            input_data,
            config=config,
            version="v2"
        ):
            # Print the event details for debugging
            logger.info(f"astream event: name='{event.get('name')}', event='{event.get('event')}', tags={event.get('tags')}")
            
            # Stream the specialist classification
            if event["event"] == "on_chain_end" and event["name"] == "route":
                output = event["data"].get("output", {})
                if isinstance(output, dict) and "specialist" in output:
                    yield {
                        "type": "specialist",
                        "data": output["specialist"]
                    }
            
            # Stream actual chat tokens generated by subagents
            elif event["event"] == "on_chat_model_stream":
                chunk = event["data"].get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    try:
                        from metrics import increment_tokens
                        increment_tokens(1)
                    except ImportError:
                        pass
                    yield {
                        "type": "token",
                        "data": chunk.content
                    }

