# Session Handoff & State Tracker

## Current Session Status
- **Phase**: Phase 6 — LangGraph Tool Registration (In Progress)
- **Agent Core Status**: Running in EKS. ECR rebuild triggered to deploy tool-enabled version.
- **Security & Gateway Status**: Vault & Kong API/AI Gateways fully running.
- **Frontend Status**: Vite React dashboard running locally at `http://localhost:5173/`.
- **Active Endpoints**:
  * **Kong Public LB**: `a659b32a9d28f421da4c4090c1d0b3d0-774720386.us-east-1.elb.amazonaws.com`
  * **ECR URL**: `818593257879.dkr.ecr.us-east-1.amazonaws.com/agent-core`
  * **Vault Endpoint**: `http://vault.default.svc.cluster.local:8200`
  * **AI Gateway**: `/v1/chat/completions` → Kong `ai-proxy` → Amazon Bedrock (`us.amazon.nova-lite-v1:0`)
  * **Chat Endpoint**: `POST /chat` on Kong public LB

## Accomplishments (Cumulative)
1. Drafted architecture spec with SOLID principles & security governance.
2. Provisioned EKS VPC, Node Groups, and IRSA permissions via Terraform.
3. Deployed HashiCorp Vault + Kong Gateway with CORS & Rate Limiting plugins.
4. Wrote FastAPI + LangGraph Agent Core container; deployed to EKS with keyless Vault SA auth.
5. Migrated model routing to Amazon Bedrock Nova Lite via Kong AI Proxy (bypasses Free Tier IP blocks).
6. Verified E2E: public `curl POST /chat` returns `200 OK` from Bedrock model.
7. Built premium React + CopilotKit dashboard (dark theme, glassmorphism, Outfit font, pulsing indicators).
8. Fixed CopilotKit API breaking changes: `useMakeCopilotReadable` → `useCopilotReadable` + `runtimeUrl`.
9. Added 4 registered tools to `app/agent.py` with ToolNode + conditional routing loop.
10. Fixed `DOCKER` Makefile macro to use Colima socket (no Docker Desktop installed).

## Phase 6 Remaining Steps
- [ ] Rebuild & push ECR image with tool-enabled `agent.py` — `make build-and-push`
- [ ] Rolling redeploy to EKS — `make deploy-agent`
- [ ] Manual verification: ask agent "what tools do you have?" and "check cluster health"

## Key Gotchas & Notes
- **Docker**: No Docker Desktop installed. Docker daemon runs via `colima`. Use `DOCKER_HOST=unix://$HOME/.colima/default/docker.sock docker ...` or `$(DOCKER)` Makefile macro.
- **langchain-core**: Must be `>=0.2.27,<0.3.0` for `langchain==0.2.12` compatibility.
- **CopilotKit**: `<CopilotKit>` provider requires `runtimeUrl` or `publicApiKey` prop — omitting it causes a blank white/black screen crash.
- **Platform flag**: Always build with `--platform linux/amd64` for EKS `x86_64` node groups (Mac M-series is `arm64`).
