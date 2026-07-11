import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from vault_client import VaultSecretsManager
from agent import LangGraphAgent
from langchain_core.messages import HumanMessage, AIMessage
# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agent-core")

app = FastAPI(title="AgentCore Service", version="1.0.0")

# Global instances initialized on startup
secrets_manager = VaultSecretsManager()
agent_orchestrator = None

class ChatRequest(BaseModel):
    prompt: str
    session_id: Optional[str] = None

class ChatResponse(BaseModel):
    response: str
    specialist: Optional[str] = None

@app.on_event("startup")
async def startup_event():
    global agent_orchestrator
    logger.info("Initializing AgentCore backend...")
    try:
        # Retrieve API key keylessly from HashiCorp Vault
        api_key = secrets_manager.get_gemini_api_key()
        logger.info("Successfully retrieved Gemini API key from Vault!")
        
        # Initialize LangGraph client with retrieved key
        agent_orchestrator = LangGraphAgent(api_key=api_key)
        logger.info("LangGraph agent compiled and ready!")
    except Exception as e:
        logger.error(f"FATAL: Failed to initialize security/LLM keys: {str(e)}")
        # We don't exit(1) immediately to allow debug shell access to container,
        # but readiness check will fail.

@app.get("/health")
def health_check():
    if agent_orchestrator is None:
        raise HTTPException(status_code=500, detail="Service uninitialized")
    return {"status": "healthy", "vault": "connected"}

@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    if agent_orchestrator is None:
        raise HTTPException(status_code=503, detail="Agent logic not initialized")
    
    try:
        session_id = request.session_id or "default"
        logger.info(f"Received prompt for session {session_id}: '{request.prompt[:30]}...'")
        response_text, specialist_key = agent_orchestrator.run(
            user_prompt=request.prompt,
            session_id=session_id
        )
        return ChatResponse(response=response_text, specialist=specialist_key)
    except Exception as e:
        logger.error(f"Error during agent runtime execution: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Agent Error: {str(e)}")

from fastapi.responses import StreamingResponse
import json

@app.post("/chat/stream")
async def chat_stream_endpoint(request: ChatRequest):
    if agent_orchestrator is None:
        raise HTTPException(status_code=503, detail="Agent logic not initialized")
    
    session_id = request.session_id or "default"
    logger.info(f"Received stream prompt for session {session_id}: '{request.prompt[:30]}...'")
    
    async def sse_generator():
        try:
            async for event in agent_orchestrator.astream(
                user_prompt=request.prompt,
                session_id=session_id
            ):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            logger.error(f"Error in stream generation: {str(e)}")
            yield f"data: {json.dumps({'type': 'error', 'data': str(e)})}\n\n"
            
    return StreamingResponse(sse_generator(), media_type="text/event-stream")

@app.get("/chat/history")
def get_chat_history(session_id: str = "default"):
    if agent_orchestrator is None:
        raise HTTPException(status_code=503, detail="Agent logic not initialized")
    
    try:
        config = {"configurable": {"thread_id": session_id}}
        state = agent_orchestrator.graph.get_state(config)
        
        history = []
        if state and state.values and "messages" in state.values:
            for msg in state.values["messages"]:
                if isinstance(msg, HumanMessage) or (hasattr(msg, "type") and msg.type == "human"):
                    history.append({"role": "user", "content": msg.content})
                elif isinstance(msg, AIMessage) or (hasattr(msg, "type") and msg.type == "ai"):
                    # We can store a specialist tag in the response message if desired,
                    # but standard content representation is cleaner.
                    history.append({"role": "assistant", "content": msg.content})
        return {"history": history}
    except Exception as e:
        logger.error(f"Error fetching stateful history: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/v1/copilotkit/info")
@app.post("/v1/copilotkit/info")
@app.post("/v1/copilotkit")
def copilotkit_info_endpoint():
    """Dummy CopilotKit backend capability handshake endpoint to satisfy frontend mount discovery."""
    return {
        "a2uiEnabled": False,
        "actions": [],
        "agents": [{"agentId": "default", "templates": []}]
    }
