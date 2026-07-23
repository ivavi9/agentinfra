import logging
import os
import json
import uuid
from datetime import datetime, timezone
import jwt
import httpx
from fastapi import FastAPI, HTTPException, Depends, Header, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from vault_client import VaultSecretsManager
from tenant_governance import PIIRedactor, TenantIsolationManager
from agent import LangGraphAgent
from langchain_core.messages import HumanMessage, AIMessage

from fastapi.middleware.cors import CORSMiddleware

_vault_secrets: dict = {}


class ApproveRequest(BaseModel):
    session_id: str
    action: str  # "approve" or "reject"


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agent-core")

app = FastAPI(title="AgentCore Service", version="1.0.0")

# Configure CORS explicitly with scoped origins (no wildcard with credentials)
allowed_origins_env = os.getenv(
    "ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000"
)
allowed_origins = [
    origin.strip() for origin in allowed_origins_env.split(",") if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global instances initialized on startup
secrets_manager = VaultSecretsManager()
agent_orchestrator = None
pipeline_orchestrator = None
COGNITO_JWKS = None
COGNITO_ISSUER = None
COGNITO_CLIENT_ID = None


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


class UserContext(BaseModel):
    user_id: str
    tenant_id: str


def verify_token(
    authorization: Optional[str] = Header(None),
    x_tenant_id: Optional[str] = Header(None),
) -> UserContext:
    """Verifies incoming JWT Cognito token and extracts user_id and tenant_id. Fail-closed by design."""
    # Explicit env flag for local development testing only
    if os.getenv("DEV_BYPASS_AUTH", "").lower() == "true":
        logger.warning("DEV_BYPASS_AUTH enabled — returning dev_user")
        t_id = x_tenant_id or "tenant-default"
        return UserContext(user_id="dev_user", tenant_id=t_id)

    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401, detail="Invalid authorization header format"
        )

    token = authorization.split(" ")[1]

    if not COGNITO_JWKS:
        logger.error("Cognito JWKS not initialized or unavailable")
        raise HTTPException(
            status_code=503,
            detail="Authentication service unavailable (JWKS uninitialized)",
        )

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
                    "e": key["e"],
                }
                break

        if not rsa_key:
            raise HTTPException(status_code=401, detail="Signing key not found in JWKS")

        # Construct public key and verify signature
        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(rsa_key)
        payload = jwt.decode(
            token,
            public_key,  # type: ignore
            algorithms=["RS256"],
            issuer=COGNITO_ISSUER,
            options={"verify_aud": False},
        )

        # Verify audience or client_id claim if client ID is configured
        if COGNITO_CLIENT_ID:
            token_client = payload.get("client_id") or payload.get("aud")
            if token_client != COGNITO_CLIENT_ID:
                raise HTTPException(
                    status_code=401, detail="Token audience/client_id mismatch"
                )

        sub = payload.get("sub")
        if not sub:
            raise HTTPException(status_code=401, detail="Token missing sub claim")

        tenant_id = (
            x_tenant_id
            or payload.get("custom:tenant_id")
            or payload.get("tenant_id")
            or "tenant-default"
        )
        return UserContext(user_id=sub, tenant_id=tenant_id)

    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"JWT Verification Exception: {e}")
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")


@app.on_event("startup")
async def startup_event():
    global agent_orchestrator, pipeline_orchestrator, _vault_secrets, COGNITO_CLIENT_ID
    logger.info("Initializing AgentCore backend...")
    try:
        # Retrieve all secrets keylessly from HashiCorp Vault
        try:
            secrets = secrets_manager.get_secrets()
            api_key = secrets["api_key"]
            logger.info("Successfully retrieved Gemini API key from Vault!")
        except Exception as vault_err:
            logger.warning(
                f"Could not connect to Vault: {vault_err}. Checking environment variables fallback..."
            )
            api_key = os.getenv("GEMINI_API_KEY") or os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "No API key found in Vault or GEMINI_API_KEY/OPENAI_API_KEY environment variables."
                )
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

        COGNITO_CLIENT_ID = secrets.get("cognito_client_id") or os.getenv(
            "COGNITO_CLIENT_ID"
        )

        # Cache secrets at module scope for downstream pipeline runners
        _vault_secrets = secrets

        # Initialize LangGraph client with retrieved key and DB configuration
        agent_orchestrator = LangGraphAgent(api_key=api_key, db_config=secrets)
        logger.info("LangGraph agent compiled and ready!")

        # Initialize pipeline graph client
        from agents.supervisor import DatabricksPipelineGraph

        pipeline_orchestrator = DatabricksPipelineGraph(
            api_key=api_key, db_config=secrets
        )
        logger.info("Databricks Pipeline state graph compiled and ready!")
    except Exception as e:
        logger.error(f"FATAL: Failed to initialize security/LLM keys: {str(e)}")


@app.get("/health")
def health_check():
    if agent_orchestrator is None:
        raise HTTPException(status_code=500, detail="Service uninitialized")
    return {"status": "healthy", "vault": "connected"}


@app.get("/config")
def get_runtime_config():
    secrets = _vault_secrets or {}
    return {
        "cognito_user_pool_id": secrets.get("cognito_user_pool_id")
        or os.getenv("COGNITO_USER_POOL_ID", ""),
        "cognito_client_id": secrets.get("cognito_client_id")
        or os.getenv("COGNITO_CLIENT_ID", ""),
        "aws_region": secrets.get("aws_region") or os.getenv("AWS_REGION", "us-east-1"),
        "api_url": os.getenv("API_URL", ""),
    }


AUDIT_STORE: List[Dict[str, Any]] = []


@app.get("/audit/logs")
def get_audit_logs(user_ctx: UserContext = Depends(verify_token)):
    """Returns immutable audit event log for the current tenant."""
    logs = [log for log in AUDIT_STORE if log.get("tenant_id") == user_ctx.tenant_id]
    return {"status": "SUCCESS", "tenant_id": user_ctx.tenant_id, "logs": logs}


@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(
    request: ChatRequest, user_ctx: UserContext = Depends(verify_token)
):
    if agent_orchestrator is None:
        raise HTTPException(status_code=503, detail="Agent logic not initialized")

    try:
        session_id = request.session_id or "default"
        thread_id = f"{user_ctx.tenant_id}:{user_ctx.user_id}:{session_id}"
        sanitized_prompt = PIIRedactor.redact_text(request.prompt)
        logger.info(
            f"Received prompt for tenant {user_ctx.tenant_id}, user {user_ctx.user_id}, session {session_id} -> thread {thread_id}"
        )

        # Audit log record
        AUDIT_STORE.append(
            TenantIsolationManager.create_audit_entry(
                tenant_id=user_ctx.tenant_id,
                actor=user_ctx.user_id,
                action="CHAT_RUN",
                resource="/chat",
                payload={
                    "prompt_hash": TenantIsolationManager.compute_hash(sanitized_prompt)
                },
            )
        )

        response_text, specialist_key = agent_orchestrator.run(
            user_prompt=sanitized_prompt, session_id=thread_id
        )
        return ChatResponse(response=response_text, specialist=specialist_key)
    except Exception as e:
        logger.error(f"Error during agent runtime execution: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Agent Error: {str(e)}")


@app.post("/chat/stream")
async def chat_stream_endpoint(
    request: ChatRequest, user_ctx: UserContext = Depends(verify_token)
):
    if agent_orchestrator is None:
        raise HTTPException(status_code=503, detail="Agent logic not initialized")

    session_id = request.session_id or "default"
    thread_id = f"{user_ctx.tenant_id}:{user_ctx.user_id}:{session_id}"
    sanitized_prompt = PIIRedactor.redact_text(request.prompt)
    logger.info(
        f"Received stream prompt for tenant {user_ctx.tenant_id}, user {user_ctx.user_id}, session {session_id} -> thread {thread_id}"
    )

    AUDIT_STORE.append(
        TenantIsolationManager.create_audit_entry(
            tenant_id=user_ctx.tenant_id,
            actor=user_ctx.user_id,
            action="CHAT_STREAM",
            resource="/chat/stream",
            payload={
                "prompt_hash": TenantIsolationManager.compute_hash(sanitized_prompt)
            },
        )
    )

    async def sse_generator():
        try:
            async for event in agent_orchestrator.astream(
                user_prompt=sanitized_prompt, session_id=thread_id
            ):
                yield f"data: {json.dumps(event)}\n\n"

            config = {"configurable": {"thread_id": thread_id}}
            state = agent_orchestrator.graph.get_state(config)
            if state and state.next:
                yield f"data: {json.dumps({'type': 'approval_required', 'next_nodes': list(state.next)})}\n\n"
        except Exception as e:
            logger.error(f"Error in stream generation: {str(e)}")
            yield f"data: {json.dumps({'type': 'error', 'data': str(e)})}\n\n"

    return StreamingResponse(sse_generator(), media_type="text/event-stream")


@app.post("/chat/approve")
async def chat_approve_endpoint(
    request: ApproveRequest, user_ctx: UserContext = Depends(verify_token)
):
    if agent_orchestrator is None:
        raise HTTPException(status_code=503, detail="Agent logic not initialized")

    thread_id = f"{user_ctx.tenant_id}:{user_ctx.user_id}:{request.session_id}"
    logger.info(
        f"Received approval response for tenant {user_ctx.tenant_id}, user {user_ctx.user_id}, session {request.session_id} -> action: {request.action}"
    )

    AUDIT_STORE.append(
        TenantIsolationManager.create_audit_entry(
            tenant_id=user_ctx.tenant_id,
            actor=user_ctx.user_id,
            action=f"CHAT_APPROVE_{request.action.upper()}",
            resource="/chat/approve",
            payload={"session_id": request.session_id, "action": request.action},
        )
    )

    if request.action == "reject":
        config = {"configurable": {"thread_id": thread_id}}
        agent_orchestrator.graph.update_state(config, None, as_node="__end__")

        async def cancel_generator():
            yield f"data: {json.dumps({'type': 'status', 'data': 'Action execution cancelled by user.'})}\n\n"

        return StreamingResponse(cancel_generator(), media_type="text/event-stream")

    async def sse_generator():
        try:
            async for event in agent_orchestrator.astream(
                user_prompt=None, session_id=thread_id
            ):
                yield f"data: {json.dumps(event)}\n\n"

            config = {"configurable": {"thread_id": thread_id}}
            state = agent_orchestrator.graph.get_state(config)
            if state and state.next:
                yield f"data: {json.dumps({'type': 'approval_required', 'next_nodes': list(state.next)})}\n\n"
        except Exception as e:
            logger.error(f"Error resuming graph from interrupt: {str(e)}")
            yield f"data: {json.dumps({'type': 'error', 'data': str(e)})}\n\n"

    return StreamingResponse(sse_generator(), media_type="text/event-stream")


@app.post("/pipeline/analyse")
async def pipeline_analyse_endpoint(
    request: PipelineAnalyseRequest, user_ctx: UserContext = Depends(verify_token)
):
    if pipeline_orchestrator is None:
        raise HTTPException(
            status_code=503, detail="Pipeline agent logic not initialized"
        )

    session_id = request.session_id or "default"
    thread_id = f"{user_ctx.tenant_id}:{user_ctx.user_id}:{session_id}"
    logger.info(
        f"Received pipeline analysis request for tenant {user_ctx.tenant_id}, user {user_ctx.user_id}, session {session_id}"
    )

    AUDIT_STORE.append(
        TenantIsolationManager.create_audit_entry(
            tenant_id=user_ctx.tenant_id,
            actor=user_ctx.user_id,
            action="PIPELINE_ANALYSE",
            resource="/pipeline/analyse",
            payload={"session_id": session_id},
        )
    )

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
            "error": None,
        },
    )

    try:
        result = pipeline_orchestrator.graph.invoke(None, config=config)
        state = pipeline_orchestrator.graph.get_state(config)
        next_nodes = list(state.next) if state else []

        return {
            "status": (
                "interrupted_for_approval"
                if "dab_generator" in next_nodes
                else "completed"
            ),
            "value_stream_json": result.get("value_stream_json", {}),
            "bronze_schema": result.get("bronze_schema", {}),
            "silver_conformed": result.get("silver_conformed", {}),
            "mapping_matrix": result.get("mapping_matrix", []),
            "validation": result.get("validation", {}),
            "error": result.get("error"),
        }
    except Exception as e:
        logger.error(f"Pipeline analysis execution error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/pipeline/approve")
async def pipeline_approve_endpoint(
    request: PipelineApproveRequest, user_ctx: UserContext = Depends(verify_token)
):
    if pipeline_orchestrator is None:
        raise HTTPException(
            status_code=503, detail="Pipeline agent logic not initialized"
        )

    thread_id = f"{user_ctx.tenant_id}:{user_ctx.user_id}:{request.session_id}"
    config = {"configurable": {"thread_id": thread_id}}
    logger.info(
        f"Received pipeline approval request for tenant {user_ctx.tenant_id}, user {user_ctx.user_id}, session {request.session_id}"
    )

    AUDIT_STORE.append(
        TenantIsolationManager.create_audit_entry(
            tenant_id=user_ctx.tenant_id,
            actor=user_ctx.user_id,
            action="PIPELINE_APPROVE",
            resource="/pipeline/approve",
            payload={
                "session_id": request.session_id,
                "mapping_count": len(request.mapping_matrix),
            },
        )
    )

    try:
        from validator import PipelineValidator

        current_state = pipeline_orchestrator.graph.get_state(config)
        bronze_schema = (
            current_state.values.get("bronze_schema", {})
            if current_state and current_state.values
            else {}
        )
        val_res = PipelineValidator.validate_mapping_matrix(
            bronze_schema, request.mapping_matrix
        )
    except Exception as val_err:
        logger.warning(f"Re-validation failed on human approved mapping: {val_err}")
        raise HTTPException(
            status_code=400, detail=f"Mapping validation error: {val_err}"
        )

    pipeline_orchestrator.graph.update_state(
        config,
        {
            "mapping_matrix": request.mapping_matrix,
            "validation": val_res,
            "approved": True,
        },
    )

    try:
        result = pipeline_orchestrator.graph.invoke(None, config=config)
        return {
            "status": "success",
            "generated_bundle_files": result.get("generated_bundle_files", {}),
            "validation": result.get("validation", val_res),
            "error": result.get("error"),
        }
    except Exception as e:
        logger.error(f"Pipeline approval resumption error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


JOBS_STORE: Dict[str, Dict[str, Any]] = {}


def _execute_async_pipeline_job(
    job_id: str,
    request: PipelineRunRequest,
    user_id: str,
    tenant_id: str,
    mappings: list,
    db_config: dict,
):
    """Async background worker task for downloading S3 assets and running Medallion ingestion."""
    JOBS_STORE[job_id]["status"] = "RUNNING"
    JOBS_STORE[job_id]["started_at"] = datetime.now(timezone.utc).isoformat()
    try:
        from pipeline_runner import PipelineRunner

        runner = PipelineRunner(db_config)
        res = runner.run_conformance(
            entity_name=request.entity_name,
            mappings=mappings,
            bucket=request.bucket_name,
            tenant_id=tenant_id,
        )
        JOBS_STORE[job_id]["status"] = "COMPLETED"
        JOBS_STORE[job_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
        JOBS_STORE[job_id]["result"] = res
    except Exception as e:
        logger.error(f"Async pipeline execution error for job {job_id}: {e}")
        JOBS_STORE[job_id]["status"] = "FAILED"
        JOBS_STORE[job_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
        JOBS_STORE[job_id]["error"] = str(e)


@app.post("/pipeline/run", status_code=202)
def run_pipeline(
    request: PipelineRunRequest,
    background_tasks: BackgroundTasks,
    user_ctx: UserContext = Depends(verify_token),
):
    if pipeline_orchestrator is None:
        raise HTTPException(
            status_code=530, detail="Pipeline agent logic not initialized"
        )

    thread_id = f"{user_ctx.tenant_id}:{user_ctx.user_id}:{request.session_id}"
    config = {"configurable": {"thread_id": thread_id}}

    state = pipeline_orchestrator.graph.get_state(config)
    if not state or not state.values or "mapping_matrix" not in state.values:
        raise HTTPException(
            status_code=400,
            detail="No conformed mappings found. Generate and approve mappings first.",
        )

    mappings = state.values["mapping_matrix"]
    if not mappings:
        raise HTTPException(
            status_code=400,
            detail="Mapping matrix is empty. Run /pipeline/analyse first.",
        )

    job_id = f"job-{uuid.uuid4().hex[:8]}"
    JOBS_STORE[job_id] = {
        "job_id": job_id,
        "status": "QUEUED",
        "user_id": user_ctx.user_id,
        "tenant_id": user_ctx.tenant_id,
        "entity_name": request.entity_name,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    AUDIT_STORE.append(
        TenantIsolationManager.create_audit_entry(
            tenant_id=user_ctx.tenant_id,
            actor=user_ctx.user_id,
            action="PIPELINE_RUN_QUEUED",
            resource=f"/pipeline/run/{job_id}",
            payload={"job_id": job_id, "entity_name": request.entity_name},
        )
    )

    background_tasks.add_task(
        _execute_async_pipeline_job,
        job_id,
        request,
        user_ctx.user_id,
        user_ctx.tenant_id,
        mappings,
        _vault_secrets,
    )

    return {
        "status": "QUEUED",
        "job_id": job_id,
        "status_url": f"/pipeline/status/{job_id}",
        "message": f"Pipeline execution job '{job_id}' queued for async background execution.",
    }


@app.get("/pipeline/status/{job_id}")
def get_pipeline_job_status(job_id: str, user_ctx: UserContext = Depends(verify_token)):
    """Returns status and execution metrics for a background pipeline run job."""
    if job_id not in JOBS_STORE:
        raise HTTPException(status_code=404, detail=f"Job ID '{job_id}' not found")
    job = JOBS_STORE[job_id]
    if job.get("tenant_id") and job["tenant_id"] != user_ctx.tenant_id:
        raise HTTPException(
            status_code=403, detail="Access denied: job belongs to another tenant"
        )
    return job


@app.get("/model/quota")
def get_model_quota(user_ctx: UserContext = Depends(verify_token)):
    """Returns daily token quota usage for the current tenant."""
    from model_router import QuotaManager

    qm = QuotaManager()
    return qm.get_tenant_quota_status(user_ctx.tenant_id)


@app.get("/pipeline/lineage/{session_id}")
def get_pipeline_lineage(
    session_id: str, user_ctx: UserContext = Depends(verify_token)
):
    """Returns field-level data lineage graph for a pipeline session."""
    from lineage_viewer import LineageGraphService

    if pipeline_orchestrator is None:
        raise HTTPException(
            status_code=503, detail="Pipeline agent logic not initialized"
        )

    thread_id = f"{user_ctx.tenant_id}:{user_ctx.user_id}:{session_id}"
    config = {"configurable": {"thread_id": thread_id}}
    state = pipeline_orchestrator.graph.get_state(config)

    mappings = []
    entity_name = "transaction"
    if state and state.values:
        mappings = state.values.get("mapping_matrix", [])

    return LineageGraphService.generate_lineage(
        entity_name=entity_name, mappings=mappings, tenant_id=user_ctx.tenant_id
    )


class DocumentParseRequest(BaseModel):
    content: str


@app.post("/document/parse")
def parse_brd_document(
    request: DocumentParseRequest, user_ctx: UserContext = Depends(verify_token)
):
    """Parses a Business Requirement Document (BRD) into structured entity specifications."""
    from document_parser import BRDDocumentParser

    return BRDDocumentParser.parse_brd_content(request.content)


@app.get("/compliance/posture")
def get_compliance_posture(user_ctx: UserContext = Depends(verify_token)):
    """Returns verified enterprise security and SOC2 compliance control matrix."""
    from compliance_manager import CompliancePostureManager

    return CompliancePostureManager.get_compliance_posture()


@app.get("/chat/history")
def get_chat_history(
    session_id: str = "default", user_ctx: UserContext = Depends(verify_token)
):
    if agent_orchestrator is None:
        raise HTTPException(status_code=503, detail="Agent logic not initialized")

    try:
        thread_id = f"{user_ctx.tenant_id}:{user_ctx.user_id}:{session_id}"
        logger.info(
            f"Retrieving stateful history for tenant {user_ctx.tenant_id}, user {user_ctx.user_id}, thread: {thread_id}"
        )
        config = {"configurable": {"thread_id": thread_id}}
        state = agent_orchestrator.graph.get_state(config)

        history = []
        if state and state.values and "messages" in state.values:
            for msg in state.values["messages"]:
                if isinstance(msg, HumanMessage) or (
                    hasattr(msg, "type") and msg.type == "human"
                ):
                    history.append({"role": "user", "content": msg.content})
                elif isinstance(msg, AIMessage) or (
                    hasattr(msg, "type") and msg.type == "ai"
                ):
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
        "agents": [{"agentId": "default", "templates": []}],
    }
