# Infrastructure Implementation Plan & Architectural Roadmap

## System Architecture Overview

```
[ React + CopilotKit UI ]
            │
            ▼
 [ Kong Gateway / Firewall ] (Auth, Rate Limiting, WAF)
            │
            ▼
 [ Kubernetes Layer (Managed EKS) ]
 ├── [ HashiCorp Vault ] (Secrets Manager)
 └── [ LangGraph Agent Core ] (Stateful Agent Graph + Checkpointer)
            │
            ▼
 [ Kong AI Gateway Proxy ]
 ├── [ Google Gemini API ] (Gemini 2.0 Flash)
 └── [ AWS Bedrock ] (Nova / Claude)
```

## Detailed Document Reference
See full design spec in [poc_architecture.md](file:///Users/avikaushik/agentinfra/memories/poc_architecture.md).

## Infrastructure Execution Mode: Ephemeral Sessions
To protect credit resources, we deploy our infrastructure as an ephemeral environment:
- **`make bootstrap`**: Deploys VPC, EKS Cluster, Kong, Vault, Postgres, and LangGraph Core.
- **`make teardown`**: Destroys all AWS resources completely.

## Phase Breakdown

- **Phase 1: Architecture, SOLID & Governance (Completed)**
  - Drafted [poc_architecture.md](file:///Users/avikaushik/agentinfra/memories/poc_architecture.md) with SOLID principles & security governance.
  - Set up statefulness directory (`memories/` & `handoff/`).

- **Phase 2: AWS Account & Environment Prerequisites (Completed)**
  - Configured EKS & VPC network via Terraform.
  - Verified local kubectl connections and credentials.

- **Phase 3: Core Security & Secrets Setup (Completed)**
  - Deployed HashiCorp Vault and Kong Gateway Ingress.
  - Setup CORS & Rate-Limiting plugin firewalls.
  - Authenticated and cached Gemini keys in Vault kv engine.

- **Phase 4: LangGraph Agent Core Deployment (Completed)**
  - Wrote FastAPI + LangGraph Agent container.
  - Configured Vault Kubernetes authentication (keyless SA auth).
  - Built and pushed platform-specific image (`linux/amd64`) to AWS ECR.
  - Deployed Agent Core pod to EKS and validated health check connections.
  - Set up Kong AI Ingress mapping OpenAI format to model backend.
  - Migrated keyless routing to Amazon Bedrock (`us.amazon.nova-lite-v1:0` model) to bypass Google AI Studio Free Tier cloud provider IP blocks, generating dynamic credential secrets via EKS Terraform.

- **Phase 5: React + CopilotKit UI Integration (Completed)**
  - Scaffolded Vite + React application with CopilotKit (`useCopilotReadable` hooks).
  - Built premium dashboard UI: dark space theme, Outfit typography, glassmorphism cards, pulsing status indicator.
  - Fixed `useMakeCopilotReadable` → `useCopilotReadable` breaking API change.
  - Added `runtimeUrl` prop to `<CopilotKit>` provider to fix black-screen crash.
  - Vite production build verified successfully (9138 modules transformed).

- **Phase 6: LangGraph Tool Registration (Completed)**
  - Registered 4 tools in `app/agent.py`: `get_infrastructure_status`, `get_agent_capabilities`, `call_health_endpoint`, `run_sub_prompt`.
  - Switched from single-node graph to ToolNode + conditional routing loop (agent → tools → agent).
  - Added `langchain==0.2.12` to `requirements.txt`; fixed `langchain-core` pin to `>=0.2.27,<0.3.0`.
  - Added `DOCKER` Makefile macro pointing to Colima socket (`~/.colima/default/docker.sock`) since Docker Desktop is not installed.
  - Rebuilt and deployed agent image to ECR.

- **Phase 7: LangGraph Multi-Agent Supervisor Architecture (Completed)**
  - Deployed `SupervisorAgent` routing node mapping incoming developer intents dynamically to specialist subagents.
  - Implemented 3 state-graph specialist nodes: `InfraAgent` (diagnostics & health), `CodeAgent` (capabilities manifest & sub-prompting), and `ResearchAgent` (concepts & explanations).
  - Wrapped tool responses in valid JSON to ensure compatibility with Kong Gateway `ai-proxy` parser.
  - Updated React UI with live reasoning details drop-down and active specialist routing badges.
  - Formulated C4 system containers and detailed setup playbooks in the root `README.md`.

- **Phase 8: Frontend Text Beautification & Markdown Rendering (Completed)**
  - Implemented a lightweight, zero-dependency custom parser in `frontend/src/App.jsx` supporting bold tokens (`**text**`), headings (`#`, `##`, `###`), inline code pills (`` `code` ``), lists (`-` or `*`), and fenced code blocks (` ```lang code ``` `).
  - Added premium styling rules in `frontend/src/App.css` (dark pre code blocks, purple inline code pills, padded list items, sub-bordered headers) to match our glassmorphism space theme.
  - Resolved `Failed to Fetch` CORS block errors by adding `global-cors` to `ai-gateway-ingress` annotations.
  - Fixed client-side React mounting crashes on reload by injecting a dev-only client mock configuration for the `"default"` agent.
  - Fixed specialist tool resolution by adding a dummy `query` parameter to no-parameter tools, and joining all reasoning and final response `AIMessage` contents in sequence.
  - Verified and captured rendering success screenshots in the browser.

- **Phase 9a: Safe Teardown & Orphan Resource Cleanup (Completed)**
  - Root cause identified: Kubernetes cloud controller creates Classic/NLBs dynamically outside of Terraform state; on cluster deletion these become orphans blocking VPC deletion with a `DependencyViolation` error.
  - Added `pre-teardown` Make target: drains all `LoadBalancer`-type Kubernetes Services via `kubectl` so the cloud controller voluntarily removes the ELBs. Includes 30s wait for ENI release. Degrades safely if kubeconfig is absent.
  - Added `purge-orphans` Make target: safety-net pass that queries the cluster VPC by name tag and force-deletes any remaining Classic ELBs, NLBs, and orphan Security Groups (with 30s ENI-release wait after ELB deletion).
  - Updated `teardown` target to chain: `pre-teardown → purge-orphans → terraform destroy → make clean`.
  - Verified: final AWS audit showed empty EKS, EC2, VPC, ELB, and NAT Gateway lists after successful run.

- **Phase 10: Conversational State Persistence (Completed)**
  - Integrated LangGraph stateful `MemorySaver` checkpointer inside `SupervisorAgent` in `app/agents/supervisor.py` to persist context across separate REST requests.
  - Refactored `SupervisorAgent` node functions (`_infra_node`, `_code_node`, `_research_node`) and specialists to accept and pass `RunnableConfig` down the execution tree.
  - Added `GET /chat/history` endpoint to FastAPI in `app/main.py` to fetch previous thread messages, and configured the frontend to recover conversation context contextually.

- **Phase 11: Real-Time Token Streaming (Completed)**
  - Replaced FastAPI blocking route with an asynchronous Server-Sent Events (SSE) generator at `POST /chat/stream`.
  - Added callback event filtering to capture `on_chat_model_stream` events from subagent completions, yielding tokens immediately.
  - Redesigned the React chat interface in `frontend/src/App.jsx` to append chunk tokens contextually in real-time, displaying dynamic badges and collapsible thought blocks.

- **Phase 12: Production Security, Checkpointers & Human-in-the-loop (Completed)**
  - Provisioned a managed AWS RDS PostgreSQL instance and an AWS Cognito User Pool via Terraform.
  - Refactored the core checkpointer mechanism in `app/agents/supervisor.py` to utilize `PostgresSaver` backed by connection pools.
  - Integrated JSON Web Token (JWT) validation middleware in FastAPI endpoints (`app/main.py`) using Cognito public JWKs to enforce secure user isolation.
  - Exposed Prometheus router metrics `/metrics` to count routing frequencies per specialist node.
  - Integrated client-side Cognito Signup, Confirm, and Sign In flows in the Vite frontend.
  - Built interactive approval interrupt overlays enabling lead developers to verify infrastructure commands and resume node execution via `/chat/approve` callback endpoints.

- **Phase 13: Databricks Ingestion & Mapping Automation (Completed)**
  - Developed five new specialist agents: Business Analyst (`BAAnalystAgent`), Data Profiler (`DataProfilerAgent`), Silver Model Conformer (`SilverModelAgent`), STM Mapper (`STMMappingAgent`), and DAB Generator (`DABGeneratorAgent`).
  - Implemented the `DatabricksPipelineGraph` state graph in `app/agents/supervisor.py` with human-in-the-loop checkpoints (`interrupt_before=["dab_generator"]`).
  - Added REST API routes `/pipeline/analyse` and `/pipeline/approve` in `app/main.py` to orchestrate multi-step pipeline compile runs.
  - Designed the "Databricks Ingest" tab in the React frontend featuring editable mapping tables, code viewers, and state timeline widgets.
  - Verified compilation logic, interrupts, and target schemas via local mock unit testing in `scratch/test_pipeline_compilation.py`.

- **Phase 14: E2E Medallion Pipeline Ingestion Validation (Completed ✅ — 2026-07-13)**
  - Added `POST /pipeline/run` endpoint in `app/main.py` backed by `PipelineRunner` (`app/pipeline_runner.py`) to ingest JSON assets from S3 into PostgreSQL Bronze & Silver tables.
  - Added `boto3>=1.34.0` to `app/requirements.txt` (was missing from container image).
  - **Fixed `pipeline_orchestrator.db_config` AttributeError (500)**: Introduced module-level `_vault_secrets: dict` cached at startup; used by `/pipeline/run` instead of non-existent orchestrator attribute.
  - **Fixed IMDS Hop-Limit (500 — "Unable to locate credentials")**: Set `HttpPutResponseHopLimit=2` on both EKS EC2 nodes via `modify-instance-metadata-options` so pods can reach the instance metadata service for keyless IAM creds. Persisted via `aws_launch_template.node` in `infra/terraform/eks.tf`.
  - **Added S3 IAM inline policy to node role**: Attached `AgentS3LandingAccess` policy scoped to `agent-infra-landing-bucket-*` on the EKS node role. Persisted as `aws_iam_role_policy.node_s3_landing_access` in Terraform.
  - **Fixed duplicate column SQL error (500)**: Replaced `conformed_columns` list with an ordered `dict` (keyed by lowercase column name) in `pipeline_runner.py`. Metadata columns `_ingested_at` and `_source_file` are only appended if not already produced by LLM mappings.
  - **Fixed stale LangGraph state collisions**: Verify script now uses a timestamp-suffixed `SESSION_ID` per run to ensure each invocation gets a fresh graph thread.
  - **Verified in-pod**: `kubectl exec` into `agent-core` pod confirmed `bronze_transaction: 5 rows`, `silver_transaction: 5 rows` with correct conformed columns (`ac_txn_id`, `customer_id_hash`, `ac_id`, `transaction_amount`, `transaction_timestamp`), SHA-256 hashed customer IDs, and DECIMAL-cast amounts.

- **Phase 15a: Security Hygiene & Engineering Guardrails (Completed ✅ — 2026-07-21)**
  - **Fail-Closed Auth Middleware**: Updated `verify_token()` in [app/main.py](file:///Users/avikaushik/agentinfra/app/main.py#L70-L127) to enforce strict JWT validation without `"default_user"` fallbacks, return 401/503 status codes, verify `aud`/`client_id` claims, and gate dev bypass behind `DEV_BYPASS_AUTH="true"`.
  - **Static Bedrock Key Elimination**: Deleted `aws_iam_user.bedrock_user` and `aws_iam_access_key.bedrock_user_key` in [infra/terraform/eks.tf](file:///Users/avikaushik/agentinfra/infra/terraform/eks.tf); scoped node group Bedrock policy from `AmazonBedrockFullAccess` to `bedrock:InvokeModel` / `bedrock:InvokeModelWithResponseStream` on foundation models.
  - **RDS Password Rotation**: Replaced hardcoded password string with Terraform `random_password.rds_password` resource in [infra/terraform/rds.tf](file:///Users/avikaushik/agentinfra/infra/terraform/rds.tf) and marked outputs sensitive.
  - **Makefile Automation**: Updated `write-secret` and `configure-bedrock-auth` targets to write dynamic RDS/Cognito secrets to Vault KV and generate keyless IMDS Kong AI Gateway secrets.
  - **Frontend Runtime Config & CORS Scoping**: Added `/config` endpoint in FastAPI, updated [frontend/src/App.jsx](file:///Users/avikaushik/agentinfra/frontend/src/App.jsx) (`npm run build` green), and removed wildcard `*` from `ALLOWED_ORIGINS` in [infra/k8s/agent-deployment.yaml](file:///Users/avikaushik/agentinfra/infra/k8s/agent-deployment.yaml) (`"http://localhost:5173,http://localhost:3000"`).
  - **Automated CI/CD & Test Suite**: Added GitHub Actions workflow [.github/workflows/ci.yml](file:///Users/avikaushik/agentinfra/.github/workflows/ci.yml) with unbypassed quality gates (`ruff`, `black`, `mypy` with 0 errors across 20 source files, `pytest` under `PYTHONPATH=app:.`, `terraform validate`, `gitleaks`) and pytest suite in `tests/` (20 passing tests).

- **Phase 17: Grounded Canonical Model Service (Completed ✅ — 2026-07-21)**
  - **Canonical Model Store & Vector Distance Scoring**: Created [app/canonical_store.py](file:///Users/avikaushik/agentinfra/app/canonical_store.py) (`CanonicalModelStore`) containing enterprise canonical entities (`INDIVIDUAL`, `DEPOSIT_ACCOUNT`, `FINANCIAL_TRANSACTION`) with character n-gram cosine vector similarity scoring in `search_attributes()`.
  - **Grounded Conformer Agent**: Updated `SilverModelAgent` in [app/agents/silver_model_agent.py](file:///Users/avikaushik/agentinfra/app/agents/silver_model_agent.py) to retrieve grounded candidates and return confidence scores for each mapped column.

- **Phase 18: Deterministic Validation, Pydantic Contracts & Eval Harness (Completed ✅ — 2026-07-21)**
  - **Pydantic Contracts & Transform DSL**: Created [app/contracts.py](file:///Users/avikaushik/agentinfra/app/contracts.py) defining output schemas across all 5 agents (`ValueStreamContract`, `BronzeSchemaContract`, `SilverConformedContract`, `MappingMatrixContract`, `DABBundleContract`) and `TransformDSL` enum.
  - **Deterministic Validator & Re-validation**: Created [app/validator.py](file:///Users/avikaushik/agentinfra/app/validator.py) (`PipelineValidator`) checking 100% column coverage, type safety, and target name collisions. Wired `PipelineValidator` node into `DatabricksPipelineGraph` in [app/agents/supervisor.py](file:///Users/avikaushik/agentinfra/app/agents/supervisor.py), exposed validation metrics in `/pipeline/analyse`, and added mandatory re-validation on human-edited mappings in `/pipeline/approve`.
  - **Bounded Repair Loop**: Implemented Pydantic contract validation with up to 3-attempt repair loops across all 5 pipeline agents ([ba_analyst_agent.py](file:///Users/avikaushik/agentinfra/app/agents/ba_analyst_agent.py), [data_profiler_agent.py](file:///Users/avikaushik/agentinfra/app/agents/data_profiler_agent.py), [silver_model_agent.py](file:///Users/avikaushik/agentinfra/app/agents/silver_model_agent.py), [stm_mapping_agent.py](file:///Users/avikaushik/agentinfra/app/agents/stm_mapping_agent.py), [dab_generator_agent.py](file:///Users/avikaushik/agentinfra/app/agents/dab_generator_agent.py)).
  - **Golden Evaluation Harness**: Created [app/eval_harness.py](file:///Users/avikaushik/agentinfra/app/eval_harness.py) (`MappingEvalHarness`) calculating precision, recall, and F1 score against golden BRD baselines.

- **Phase 19: Real Execution Target & Medallion Pipeline Engine (Completed ✅ — 2026-07-21)**
  - **True Medallion Architecture**: Updated [app/pipeline_runner.py](file:///Users/avikaushik/agentinfra/app/pipeline_runner.py) for raw append-only Bronze ingestion, primary-key MERGE/upsert Silver ingestion (`ON CONFLICT DO UPDATE`), case-insensitive column lookup, and DQ row quarantine table (`quarantine_*`).
  - **Primary Key Constraint Safety**: Added schema inspection of `information_schema.table_constraints` in PostgreSQL to preserve existing table PRIMARY KEY constraints on re-runs and prevent `ON CONFLICT` mismatch errors. Tested directly with mock DB connection in [tests/test_pipeline_runner.py](file:///Users/avikaushik/agentinfra/tests/test_pipeline_runner.py).

- **Model Context Protocol (MCP) Enterprise Gateway & Multi-Server Suite (Completed ✅ — 2026-07-21)**
  - **MCP Gateway Control Plane**: Created [app/mcp_gateway.py](file:///Users/avikaushik/agentinfra/app/mcp_gateway.py) (`MCPGatewayControlPlane`) acting as unified JSON-RPC proxy, RBAC policy enforcer (`admin`, `developer`, `analyst` roles), and tool aggregator (`GET /mcp/v1/tools`, `POST /mcp/v1/call`, `GET /mcp/v1/health`).
  - **FastMCP S3 Server**: Created [app/mcp_s3_server.py](file:///Users/avikaushik/agentinfra/app/mcp_s3_server.py) (`MCPS3Server`) providing `s3_discover_landing_bucket`, `s3_list_raw_assets`, and `s3_read_json_records` tools via keyless EKS Pod IRSA `boto3`.
  - **FastMCP Postgres Server**: Created [app/mcp_postgres_server.py](file:///Users/avikaushik/agentinfra/app/mcp_postgres_server.py) (`MCPPostgresServer`) providing `postgres_inspect_schema`, `postgres_execute_conformance`, and `postgres_get_quarantine_stats` tools.
  - **FastMCP Databricks Server**: Created [app/mcp_databricks_server.py](file:///Users/avikaushik/agentinfra/app/mcp_databricks_server.py) (`MCPDatabricksServer`) providing `dab_validate_bundle`, `dlt_generate_pipeline_spec`, and `dlt_get_pipeline_status` tools.
  - **FastMCP Vault Server**: Created [app/mcp_vault_server.py](file:///Users/avikaushik/agentinfra/app/mcp_vault_server.py) (`MCPVaultServer`) providing `vault_fetch_secret` and `vault_audit_access_log` keyless governance tools.
  - **Async Ingestion Offloading**: Updated [app/main.py](file:///Users/avikaushik/agentinfra/app/main.py) so `/pipeline/run` returns HTTP 202 Accepted immediately with a unique `job_id` and offloads heavy S3/Postgres operations to FastAPI `BackgroundTasks`. Added `GET /pipeline/status/{job_id}` endpoint to track real-time job execution state (`QUEUED` → `RUNNING` → `COMPLETED` / `FAILED`).
  - **Kubernetes Gateway Deployment**: Created [infra/k8s/mcp-gateway-deployment.yaml](file:///Users/avikaushik/agentinfra/infra/k8s/mcp-gateway-deployment.yaml) deploying `mcp-gateway` microservice on port 8085 with liveness/readiness probes.
  - **Complete MCP Test Suite**: Added unit tests in [tests/test_mcp_gateway.py](file:///Users/avikaushik/agentinfra/tests/test_mcp_gateway.py), [tests/test_mcp_servers.py](file:///Users/avikaushik/agentinfra/tests/test_mcp_servers.py), and [tests/test_mcp_s3_server.py](file:///Users/avikaushik/agentinfra/tests/test_mcp_s3_server.py) (**30 total passing tests across suite**).

## Planned Next Phases

- **Phase 15b: Full Identity & Transport Hardening** — Dedicated per-workload IRSA ServiceAccounts, production Raft Vault auto-unseal, and HTTPS edge TLS certs.
- **Phase 16: Multi-Tenant Data Governance & RLS** — Postgres Row-Level Security on tenant state, Cognito group custom claims, and immutable state audit log.
- **Phase 20: Model Router & Cost Tiering** — Model routing (Claude for reasoning/codegen vs Haiku/Nova for cheap steps), per-tenant token quotas, and run cost tracking.

