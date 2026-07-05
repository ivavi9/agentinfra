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

- **Phase 5: React + CopilotKit UI Integration (In Progress)**
  - Scaffold a React application using CopilotKit for interactive co-agent chat interface.
  - Set up CopilotKit endpoint to route chat completions traffic to the public Kong Gateway proxy.
  - Style the user interface with premium modern aesthetics (vibrant color tokens, Outfit typography, smooth CSS transitions, glassmorphism cards).

