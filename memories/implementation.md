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

