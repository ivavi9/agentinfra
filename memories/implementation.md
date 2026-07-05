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

## Planned Next Phases

- **Phase 10: Conversational State Persistence** — LangGraph `PostgresSaver` checkpointer backed by RDS/DynamoDB; client-generated `thread_id` header for multi-session memory.
- **Phase 11: Real-Time Token Streaming** — FastAPI `StreamingResponse` with SSE; LangGraph `.astream_events()` for incremental token delivery to React UI.
- **Phase 12: Specialist Observability & Logging** — Prometheus + Grafana or LangSmith; specialist routing frequency dashboard; Diagnostics tab in React.
- **Phase 13: Write-Access Specialist Operations** — `InfraAgent` kubectl read-only pod log exec; `CodeAgent` repository read access for PR drafts from chat.
