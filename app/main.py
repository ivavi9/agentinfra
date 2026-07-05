import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from vault_client import VaultSecretsManager
from agent import LangGraphAgent

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
        logger.info(f"Received prompt: '{request.prompt[:30]}...'")
        response_text = agent_orchestrator.run(user_prompt=request.prompt)
        return ChatResponse(response=response_text)
    except Exception as e:
        logger.error(f"Error during agent runtime execution: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Agent Error: {str(e)}")
