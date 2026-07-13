import logging
import os
import json
import jwt
import httpx
from fastapi import FastAPI, HTTPException, Depends, Header, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List
from vault_client import VaultSecretsManager
from agent import LangGraphAgent
from langchain_core.messages import HumanMessage, AIMessage

class ApproveRequest(BaseModel):
    session_id: str
    action: str # "approve" or "reject"

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agent-core")

app = FastAPI(title="AgentCore Service", version="1.0.0")

# Global instances initialized on startup
secrets_manager = VaultSecretsManager()
agent_orchestrator = None
pipeline_orchestrator = None
COGNITO_JWKS = None
COGNITO_ISSUER = None

class ChatRequest(BaseModel):
    prompt: str
    session_id: Optional[str] = None

class PipelineAnalyseRequest(BaseModel):
    brd_document: str
    session_id: Optional[str] = None

class PipelineApproveRequest(BaseModel):
    session_id: str
    mapping_matrix: List[dict]

class PipelineRunRequest(BaseModel):
    session_id: str
    bucket_name: Optional[str] = None
    entity_name: str

class ChatResponse(BaseModel):
    response: str
    specialist: Optional[str] = None

async def load_jwks(issuer_url: str):
    global COGNITO_JWKS, COGNITO_ISSUER
    try:
        COGNITO_ISSUER = issuer_url
        jwks_url = f"{issuer_url}/.well-known/jwks.json"
        logger.info(f"Loading Cognito JWKS from: {jwks_url}...")
        async with httpx.AsyncClient() as client:
            resp = await client.get(jwks_url)
            if resp.status_code == 200:
                COGNITO_JWKS = resp.json()
                logger.info("Successfully cached Cognito JWKS keys!")
            else:
                logger.error(f"Failed to fetch Cognito JWKS: status={resp.status_code}")
    except Exception as e:
        logger.error(f"Error loading JWKS keys: {e}")

def verify_token(authorization: Optional[str] = Header(None)) -> str:
    """Verifies incoming JWT Cognito token and extracts user_id (sub)."""
    if not authorization:
        # Fallback to default user for curl / dev queries
        return "default_user"
    
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header format")
        
    token = authorization.split(" ")[1]
    
    if not COGNITO_JWKS:
        logger.warning("JWKS not loaded. Bypassing verification (debug mode).")
        return "default_user"
        
    try:
        # Decode header to find key ID (kid)
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        if not kid:
            raise HTTPException(status_code=401, detail="Header missing kid claim")
            
        # Find matching key in JWKS
        rsa_key = None
        for key in COGNITO_JWKS.get("keys", []):
            if key["kid"] == kid:
                rsa_key = {
                    "kty": key["kty"],
                    "kid": key["kid"],
                    "use": key["use"],
                    "alg": key["alg"],
                    "n": key["n"],
                    "e": key["e"]
                }
                break
                
        if not rsa_key:
            raise HTTPException(status_code=401, detail="Signing key not found in JWKS")
            
        # Construct public key and verify signature
        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(rsa_key)
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            issuer=COGNITO_ISSUER,
            options={"verify_aud": False}
        )
        
        # Return sub (user ID)
        return payload.get("sub") or "default_user"
        
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except Exception as e:
        logger.error(f"JWT Verification failed: {e}")
        raise HTTPException(status_code=401, detail=f"JWT invalid: {str(e)}")

@app.on_event("startup")
async def startup_event():
    global agent_orchestrator, pipeline_orchestrator
    logger.info("Initializing AgentCore backend...")
    try:
        # Retrieve all secrets keylessly from HashiCorp Vault
        try:
            secrets = secrets_manager.get_secrets()
            api_key = secrets["api_key"]
            logger.info("Successfully retrieved Gemini API key from Vault!")
        except Exception as vault_err:
            logger.warning(f"Could not connect to Vault: {vault_err}. Checking environment variables fallback...")
            api_key = os.getenv("GEMINI_API_KEY") or os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise RuntimeError("No API key found in Vault or GEMINI_API_KEY/OPENAI_API_KEY environment variables.")
            secrets = {
                "api_key": api_key,
                "db_host": os.getenv("DB_HOST"),
                "db_port": os.getenv("DB_PORT", "5432"),
                "db_name": os.getenv("DB_NAME"),
                "db_user": os.getenv("DB_USER"),
                "db_password": os.getenv("DB_PASSWORD"),
            }
        
        # Pre-load JWKS keys for Cognito validation
        cognito_url = secrets.get("cognito_endpoint")
        if cognito_url:
            await load_jwks(cognito_url)
        
        # Initialize LangGraph client with retrieved key and DB configuration
        agent_orchestrator = LangGraphAgent(api_key=api_key, db_config=secrets)
        logger.info("LangGraph agent compiled and ready!")

        # Initialize pipeline graph client
        from agents.supervisor import DatabricksPipelineGraph
        pipeline_orchestrator = DatabricksPipelineGraph(api_key=api_key, db_config=secrets)
        logger.info("Databricks Pipeline state graph compiled and ready!")
    except Exception as e:
        logger.error(f"FATAL: Failed to initialize security/LLM keys: {str(e)}")

@app.get("/health")
def health_check():
    if agent_orchestrator is None:
        raise HTTPException(status_code=500, detail="Service uninitialized")
    return {"status": "healthy", "vault": "connected"}

@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest, user_id: str = Depends(verify_token)):
    if agent_orchestrator is None:
        raise HTTPException(status_code=503, detail="Agent logic not initialized")
    
    try:
        session_id = request.session_id or "default"
        thread_id = f"{user_id}:{session_id}"
        logger.info(f"Received prompt for user {user_id}, session {session_id} -> thread {thread_id}: '{request.prompt[:30]}...'")
        response_text, specialist_key = agent_orchestrator.run(
            user_prompt=request.prompt,
            session_id=thread_id
        )
        return ChatResponse(response=response_text, specialist=specialist_key)
    except Exception as e:
        logger.error(f"Error during agent runtime execution: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Agent Error: {str(e)}")

@app.post("/chat/stream")
async def chat_stream_endpoint(request: ChatRequest, user_id: str = Depends(verify_token)):
    if agent_orchestrator is None:
        raise HTTPException(status_code=503, detail="Agent logic not initialized")
    
    session_id = request.session_id or "default"
    thread_id = f"{user_id}:{session_id}"
    logger.info(f"Received stream prompt for user {user_id}, session {session_id} -> thread {thread_id}: '{request.prompt[:30]}...'")
    
    async def sse_generator():
        try:
            async for event in agent_orchestrator.astream(
                user_prompt=request.prompt,
                session_id=thread_id
            ):
                yield f"data: {json.dumps(event)}\n\n"
            
            # Check if graph has paused execution at an interrupt node
            config = {"configurable": {"thread_id": thread_id}}
            state = agent_orchestrator.graph.get_state(config)
            if state and state.next:
                logger.info(f"Graph execution paused at interrupt node: {state.next}. Requiring user approval.")
                yield f"data: {json.dumps({'type': 'approval_required', 'next_nodes': list(state.next)})}\n\n"
        except Exception as e:
            logger.error(f"Error in stream generation: {str(e)}")
            yield f"data: {json.dumps({'type': 'error', 'data': str(e)})}\n\n"
            
    return StreamingResponse(sse_generator(), media_type="text/event-stream")

@app.post("/chat/approve")
async def chat_approve_endpoint(request: ApproveRequest, user_id: str = Depends(verify_token)):
    if agent_orchestrator is None:
        raise HTTPException(status_code=503, detail="Agent logic not initialized")
    
    thread_id = f"{user_id}:{request.session_id}"
    logger.info(f"Received approval response for user {user_id}, session {request.session_id} -> action: {request.action}")
    
    if request.action == "reject":
        # Cancel the pending run by updating state to end
        config = {"configurable": {"thread_id": thread_id}}
        agent_orchestrator.graph.update_state(config, None, as_node="__end__")
        
        async def cancel_generator():
            yield f"data: {json.dumps({'type': 'status', 'data': 'Action execution cancelled by user.'})}\n\n"
        return StreamingResponse(cancel_generator(), media_type="text/event-stream")
        
    # If approved, resume the graph!
    async def sse_generator():
        try:
            # Pass None as prompt to resume graph from interrupt
            async for event in agent_orchestrator.astream(
                user_prompt=None,
                session_id=thread_id
            ):
                yield f"data: {json.dumps(event)}\n\n"
                
            # After resume, check if there are further interrupts
            config = {"configurable": {"thread_id": thread_id}}
            state = agent_orchestrator.graph.get_state(config)
            if state and state.next:
                yield f"data: {json.dumps({'type': 'approval_required', 'next_nodes': list(state.next)})}\n\n"
        except Exception as e:
            logger.error(f"Error resuming graph from interrupt: {str(e)}")
            yield f"data: {json.dumps({'type': 'error', 'data': str(e)})}\n\n"
            
    return StreamingResponse(sse_generator(), media_type="text/event-stream")

@app.post("/pipeline/analyse")
async def pipeline_analyse_endpoint(request: PipelineAnalyseRequest, user_id: str = Depends(verify_token)):
    if pipeline_orchestrator is None:
        raise HTTPException(status_code=503, detail="Pipeline agent logic not initialized")
    
    session_id = request.session_id or "default"
    thread_id = f"{user_id}:{session_id}"
    logger.info(f"Received pipeline analysis request for user {user_id}, session {session_id}")
    
    # Initialize state for this thread
    config = {"configurable": {"thread_id": thread_id}}
    pipeline_orchestrator.graph.update_state(
        config,
        {
            "brd_document": request.brd_document,
            "value_stream_json": {},
            "bronze_schema": {},
            "silver_conformed": {},
            "mapping_matrix": [],
            "approved": False,
            "generated_bundle_files": {},
            "error": None
        }
    )
    
    try:
        # Run graph until the interrupt breakpoint (before dab_generator)
        result = pipeline_orchestrator.graph.invoke(None, config=config)
        
        # Check if paused at dab_generator
        state = pipeline_orchestrator.graph.get_state(config)
        next_nodes = list(state.next) if state else []
        
        return {
            "status": "interrupted_for_approval" if "dab_generator" in next_nodes else "completed",
            "value_stream_json": result.get("value_stream_json", {}),
            "bronze_schema": result.get("bronze_schema", {}),
            "silver_conformed": result.get("silver_conformed", {}),
            "mapping_matrix": result.get("mapping_matrix", []),
            "error": result.get("error")
        }
    except Exception as e:
        logger.error(f"Pipeline analysis execution error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/pipeline/approve")
async def pipeline_approve_endpoint(request: PipelineApproveRequest, user_id: str = Depends(verify_token)):
    if pipeline_orchestrator is None:
        raise HTTPException(status_code=530, detail="Pipeline agent logic not initialized")
    
    thread_id = f"{user_id}:{request.session_id}"
    config = {"configurable": {"thread_id": thread_id}}
    logger.info(f"Received pipeline approval request for user {user_id}, session {request.session_id}")
    
    # Update target state mappings and set approved = True
    pipeline_orchestrator.graph.update_state(
        config,
        {
            "mapping_matrix": request.mapping_matrix,
            "approved": True
        }
    )
    
    try:
        # Resume graph execution (input None resumes from interrupt)
        result = pipeline_orchestrator.graph.invoke(None, config=config)
        return {
            "status": "success",
            "generated_bundle_files": result.get("generated_bundle_files", {}),
            "error": result.get("error")
        }
    except Exception as e:
        logger.error(f"Pipeline approval resumption error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/pipeline/run")
def run_pipeline(request: PipelineRunRequest, user_id: str = Depends(verify_token)):
    if pipeline_orchestrator is None:
        raise HTTPException(status_code=503, detail="Pipeline agent logic not initialized")

    thread_id = f"{user_id}:{request.session_id}"
    config = {"configurable": {"thread_id": thread_id}}
    
    # Retrieve conformed mappings from state checkpointer
    state = pipeline_orchestrator.graph.get_state(config)
    if not state or not state.values or "mapping_matrix" not in state.values:
        raise HTTPException(status_code=400, detail="No conformed mappings found. Generate and approve mappings first.")

    mappings = state.values["mapping_matrix"]
    db_config = pipeline_orchestrator.db_config

    try:
        from pipeline_runner import PipelineRunner
        runner = PipelineRunner(db_config)
        res = runner.run_conformance(
            entity_name=request.entity_name,
            mappings=mappings,
            bucket=request.bucket_name
        )
        return res
    except Exception as e:
        logger.error(f"Pipeline execution run error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/metrics")
def metrics_endpoint():
    from metrics import get_prometheus_metrics
    return Response(content=get_prometheus_metrics(), media_type="text/plain; version=0.0.4")

@app.get("/chat/history")
def get_chat_history(session_id: str = "default", user_id: str = Depends(verify_token)):
    if agent_orchestrator is None:
        raise HTTPException(status_code=503, detail="Agent logic not initialized")
    
    try:
        thread_id = f"{user_id}:{session_id}"
        logger.info(f"Retrieving stateful history for thread: {thread_id}")
        config = {"configurable": {"thread_id": thread_id}}
        state = agent_orchestrator.graph.get_state(config)
        
        history = []
        if state and state.values and "messages" in state.values:
            for msg in state.values["messages"]:
                if isinstance(msg, HumanMessage) or (hasattr(msg, "type") and msg.type == "human"):
                    history.append({"role": "user", "content": msg.content})
                elif isinstance(msg, AIMessage) or (hasattr(msg, "type") and msg.type == "ai"):
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
