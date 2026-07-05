import os
from typing import TypedDict, List
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END

# Define state structure
class AgentState(TypedDict):
    messages: List[BaseMessage]

class LangGraphAgent:
    def __init__(self, api_key: str):
        # AI Gateway endpoint (Kong proxy IP internally in K8s)
        gateway_url = os.getenv("AI_GATEWAY_URL", "http://kong-kong-proxy.default.svc.cluster.local:80/v1")
        
        # Configure client using DIP - points to local Gateway, not direct Google SDK
        self.llm = ChatOpenAI(
            base_url=gateway_url,
            api_key=api_key,
            model="us.amazon.nova-lite-v1:0", # Handled & routed by Kong AI Gateway
            temperature=0.7,
            streaming=False
        )
        self.workflow = self._build_graph()

    def _agent_node(self, state: AgentState) -> dict:
        """Invokes LLM client via unified AI Gateway proxy."""
        messages = state["messages"]
        response = self.llm.invoke(messages)
        return {"messages": [response]}

    def _build_graph(self):
        """Compiles the state machine graph using LangGraph."""
        builder = StateGraph(AgentState)
        
        # Add core decision/action node
        builder.add_node("agent", self._agent_node)
        
        # Set flow paths
        builder.set_entry_point("agent")
        builder.add_edge("agent", END)
        
        # Compile state machine
        return builder.compile()

    def run(self, user_prompt: str, history: List[BaseMessage] = None) -> str:
        """Executes the agent state graph and returns the text response."""
        messages = history or []
        messages.append(HumanMessage(content=user_prompt))
        
        # Run state graph synchronously
        result = self.workflow.invoke({"messages": messages})
        
        # Extract last AI message content
        last_message = result["messages"][-1]
        return last_message.content
