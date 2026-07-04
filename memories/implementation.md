# Infrastructure Implementation Plan & Architectural Roadmap

## System Architecture Overview

```
[ React + CopilotKit UI ]
            │
            ▼
 [ Kong Gateway / Firewall ] (Auth, Rate Limiting, WAF)
            │
            ▼
 [ Kubernetes Layer (EKS / k3s) ]
 ├── [ HashiCorp Vault ] (Secrets Manager)
 └── [ LangGraph Agent Core ] (Stateful Agent Graph + Checkpointer)
            │
            ▼
 [ SOLID LLM Adapter ]
 ├── [ Google Gemini API ] (Gemini 2.0 Flash)
 └── [ AWS Bedrock ] (Nova / Claude)
```

## Detailed Document Reference
See full design spec in [poc_architecture.md](file:///Users/avikaushik/agentinfra/memories/poc_architecture.md).

## Phase Breakdown

- **Phase 1: Architecture, SOLID & Governance (Completed)**
  - Drafted [poc_architecture.md](file:///Users/avikaushik/agentinfra/memories/poc_architecture.md) with SOLID principles & security governance.
  - Set up statefulness directory (`memories/` & `handoff/`).

- **Phase 2: AWS Account & Environment Prerequisites (Next)**
  - AWS CLI configuration & credential setup.
  - Region selection, IAM User/Role permissions, VPC/Subnet strategy.
  - Option selection: Managed EKS vs k3s on EC2 for budget optimization.

- **Phase 3: Core Security & Secrets Setup**
  - HashiCorp Vault deployment (Vault Helm chart or local container).
  - Kong Gateway installation with rate-limiting & JWT auth plugins.

- **Phase 4: LangGraph Agent Core & SOLID Adapter**
  - Develop Python/TypeScript LangGraph agent with state checkpointer.
  - Implement `ILLMProviderAdapter` for Google Gemini 2.0 Flash & AWS Bedrock.

- **Phase 5: React + CopilotKit UI Integration**
  - Lightweight React application with CopilotKit hooks talking to Kong Gateway.

## Financial Strategy ($160-$180 Credits)
- **k3s on EC2 (Recommended)**: ~$15–$25/month -> 6-8 months runway.
- **Managed EKS**: ~$73/month control plane + EC2 nodes -> ~2 months runway.
