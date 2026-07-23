import os
import logging
from pydantic import SecretStr
from typing import TypedDict, Annotated, List, Optional, Any
from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

from .infra_agent import InfraAgent
from .code_agent import CodeAgent
from .research_agent import ResearchAgent
from .ba_analyst_agent import BAAnalystAgent
from .data_profiler_agent import DataProfilerAgent
from .silver_model_agent import SilverModelAgent
from .stm_mapping_agent import STMMappingAgent
from .dab_generator_agent import DABGeneratorAgent
from model_router import ModelRouter
from db import get_shared_postgres_pool

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


class SupervisorState(TypedDict, total=False):
    messages: Annotated[List[BaseMessage], add_messages]
    specialist: Optional[str]


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
            "AI_GATEWAY_URL", "http://kong-kong-proxy.default.svc.cluster.local:80/v1"
        )

        base_model = ModelRouter.get_model_for_task("routing")

        # Enable streaming support for the base LLM
        base_llm = ChatOpenAI(
            base_url=gateway_url,
            api_key=SecretStr(api_key),
            model=base_model,
            temperature=0.7,
            streaming=True,
        )

        # Router LLM — low temperature, sync classification
        self.router_llm = ChatOpenAI(
            base_url=gateway_url,
            api_key=SecretStr(api_key),
            model=base_model,
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
            },
        )

        # Connect specialists to the end point
        builder.add_edge("infra", END)
        builder.add_edge("code", END)
        builder.add_edge("research", END)

        # Configure RDS PostgreSQL checkpointer with in-memory fallback
        self.memory: Any = None
        if db_config and db_config.get("db_host"):
            try:
                logger.info(
                    f"Connecting to consolidated Postgres checkpointer pool: host={db_config['db_host']}"
                )
                self.pool = get_shared_postgres_pool(db_config, max_size=10)
                if self.pool:
                    self.memory = PostgresSaver(self.pool)  # type: ignore
                    self.memory.setup()
                    logger.info(
                        "SupervisorAgent successfully compiled with PostgresSaver checkpointer"
                    )
                else:
                    self.memory = MemorySaver()
            except Exception as e:
                logger.error(
                    f"Failed to initialize PostgresSaver checkpointer: {e}. Falling back to MemorySaver."
                )
                self.memory = MemorySaver()
        else:
            logger.info(
                "Initializing SupervisorAgent with local MemorySaver checkpointer"
            )
            self.memory = MemorySaver()

        # Set human-in-the-loop interrupts before EKS infrastructure specialist runs
        self.graph = builder.compile(
            checkpointer=self.memory, interrupt_before=["infra"]
        )

    def _route(self, user_prompt: str) -> str:
        """Uses the router LLM to classify intent and select a specialist."""
        routing_messages = [
            SystemMessage(content=ROUTING_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]
        response = self.router_llm.invoke(routing_messages)
        decision = str(response.content).strip().upper()

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
        logger.warning(
            f"Could not classify intent, falling back to RESEARCH. Decision: {decision!r}"
        )
        try:
            from metrics import increment_route

            increment_route("RESEARCH")
        except ImportError:
            pass
        return "RESEARCH"

    def _route_node(self, state: SupervisorState) -> dict:
        # Find the last human message in history to classify intent
        user_prompt = ""
        for msg in reversed(state.get("messages", [])):
            if isinstance(msg, HumanMessage) or (
                hasattr(msg, "role") and msg.role == "user"
            ):
                user_prompt = str(msg.content)
                break

        if not user_prompt:
            user_prompt = "explain capabilities"

        specialist_key = self._route(user_prompt)
        return {"specialist": specialist_key}

    def _route_decision(self, state: SupervisorState) -> str:
        return state.get("specialist") or "RESEARCH"

    async def _infra_node(self, state: SupervisorState, config: RunnableConfig) -> dict:
        response = await self.infra_agent.arun(state["messages"], config)
        return {"messages": [AIMessage(content=response)]}

    async def _code_node(self, state: SupervisorState, config: RunnableConfig) -> dict:
        response = await self.code_agent.arun(state["messages"], config)
        return {"messages": [AIMessage(content=response)]}

    async def _research_node(
        self, state: SupervisorState, config: RunnableConfig
    ) -> dict:
        response = await self.research_agent.arun(state["messages"], config)
        return {"messages": [AIMessage(content=response)]}

    def run(self, user_prompt: Optional[str], session_id: str = "default") -> tuple:
        """
        Runs the state graph synchronously for compatibility.
        """
        config = {"configurable": {"thread_id": session_id}}
        input_data: Any = (
            {"messages": [HumanMessage(content=user_prompt)]}
            if user_prompt is not None
            else None
        )
        result = self.graph.invoke(input_data, config=config)  # type: ignore
        last_msg = result["messages"][-1]
        return last_msg.content, result.get("specialist", "RESEARCH")

    async def astream(self, user_prompt: Optional[str], session_id: str = "default"):
        """
        Asynchronously streams LLM token events and specialist routing choices.
        """
        config = {"configurable": {"thread_id": session_id}}
        input_data: Any = (
            {"messages": [HumanMessage(content=user_prompt)]}
            if user_prompt is not None
            else None
        )

        async for event in self.graph.astream_events(
            input_data, config=config, version="v2"  # type: ignore
        ):
            # Print the event details for debugging
            logger.info(
                f"astream event: name='{event.get('name')}', event='{event.get('event')}', tags={event.get('tags')}"
            )

            # Stream the specialist classification
            if event["event"] == "on_chain_end" and event["name"] == "route":
                output: Any = event["data"].get("output", {})
                if isinstance(output, dict) and "specialist" in output:
                    yield {"type": "specialist", "data": output["specialist"]}

            # Stream actual chat tokens generated by subagents
            elif event["event"] == "on_chat_model_stream":
                chunk = event["data"].get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    try:
                        from metrics import increment_tokens

                        increment_tokens(1)
                    except ImportError:
                        pass
                    yield {"type": "token", "data": chunk.content}


class PipelineState(TypedDict):
    brd_document: str
    value_stream_json: dict
    bronze_schema: dict
    silver_conformed: dict
    mapping_matrix: list
    approved: bool
    generated_bundle_files: dict
    error: Optional[str]


class DatabricksPipelineGraph:
    """
    State graph orchestrating the translation of BRDs into Databricks Asset Bundles
    using intermediate Business Analyst, Profiler, Conformer, and STM Mapping agents.
    """

    def __init__(self, api_key: str, db_config: Optional[dict] = None):
        gateway_url = os.getenv(
            "AI_GATEWAY_URL", "http://kong-kong-proxy.default.svc.cluster.local:80/v1"
        )
        ba_model = ModelRouter.get_model_for_task("ba_analysis")
        codegen_model = ModelRouter.get_model_for_task("codegen")

        llm_ba = ChatOpenAI(
            base_url=gateway_url,
            api_key=SecretStr(api_key),
            model=ba_model,
            temperature=0.0,
            streaming=False,
        )
        llm_codegen = ChatOpenAI(
            base_url=gateway_url,
            api_key=SecretStr(api_key),
            model=codegen_model,
            temperature=0.0,
            streaming=False,
        )

        self.ba_analyst = BAAnalystAgent(llm_ba)
        self.data_profiler = DataProfilerAgent(llm_ba)
        self.silver_model = SilverModelAgent(llm_ba)
        self.stm_mapping = STMMappingAgent(llm_codegen)
        self.dab_generator = DABGeneratorAgent(llm_codegen)

        # Build Graph
        builder = StateGraph(PipelineState)
        builder.add_node("ba_analyst", self._ba_analyst_node)
        builder.add_node("profiler", self._profiler_node)
        builder.add_node("conformer", self._conformer_node)
        builder.add_node("mapper", self._mapper_node)
        builder.add_node("validator", self._validator_node)
        builder.add_node("dab_generator", self._dab_generator_node)

        builder.set_entry_point("ba_analyst")
        builder.add_edge("ba_analyst", "profiler")
        builder.add_edge("profiler", "conformer")
        builder.add_edge("conformer", "mapper")
        builder.add_edge("mapper", "validator")

        builder.add_edge("validator", "dab_generator")
        builder.add_edge("dab_generator", END)

        # Configure RDS PostgreSQL checkpointer with local memory fallback
        self.memory: Any = None
        if db_config and db_config.get("db_host"):
            try:
                self.pool = get_shared_postgres_pool(db_config, max_size=10)
                if self.pool:
                    self.memory = PostgresSaver(self.pool)  # type: ignore
                    self.memory.setup()
                else:
                    self.memory = MemorySaver()
            except Exception as e:
                logger.error(
                    f"Pipeline PostgresSaver failed: {e}. Falling back to MemorySaver."
                )
                self.memory = MemorySaver()
        else:
            self.memory = MemorySaver()

        # Compile specifying the interrupt before the DAB Generator node
        self.graph = builder.compile(
            checkpointer=self.memory, interrupt_before=["dab_generator"]
        )

    def _ba_analyst_node(self, state: PipelineState) -> dict:
        try:
            res = self.ba_analyst.analyze_brd(state["brd_document"])
            return {"value_stream_json": res}
        except Exception as e:
            return {"error": f"BAAnalyst error: {e}"}

    def _profiler_node(self, state: PipelineState) -> dict:
        try:
            res = self.data_profiler.profile_schema(state["value_stream_json"])
            return {"bronze_schema": res}
        except Exception as e:
            return {"error": f"Profiler error: {e}"}

    def _conformer_node(self, state: PipelineState) -> dict:
        try:
            res = self.silver_model.conform_model(state["bronze_schema"])
            return {"silver_conformed": res}
        except Exception as e:
            return {"error": f"Conformer error: {e}"}

    def _mapper_node(self, state: PipelineState) -> dict:
        try:
            res = self.stm_mapping.generate_mapping(
                state["bronze_schema"], state["silver_conformed"]
            )
            return {"mapping_matrix": res.get("mappings", []), "approved": False}
        except Exception as e:
            return {"error": f"Mapper error: {e}"}

    def _validator_node(self, state: PipelineState) -> dict:
        try:
            from validator import PipelineValidator

            val_res = PipelineValidator.validate_mapping_matrix(
                state.get("bronze_schema", {}), state.get("mapping_matrix", [])
            )
            return {"validation": val_res}
        except Exception as e:
            logger.error(f"Pipeline validation error: {e}")
            return {"error": f"Validator error: {e}"}

    def _dab_generator_node(self, state: PipelineState) -> dict:
        try:
            res = self.dab_generator.generate_bundle(state["mapping_matrix"])
            return {"generated_bundle_files": res.get("files", {})}
        except Exception as e:
            return {"error": f"DAB generator error: {e}"}
