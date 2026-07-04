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
 [ SOLID LLM Adapter ]
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

- **Phase 2: AWS Account & Environment Prerequisites (Next)**
  - AWS CLI configuration & credential setup.
  - Region selection, IAM User/Role permissions, VPC/Subnet strategy.
  - Write Terraform scripts for the EKS Cluster and VPC setup.
  - Create automation scripts (`Makefile`) to bootstrap and teardown in a single step.

- **Phase 3: Core Security & Secrets Setup**
  - HashiCorp Vault deployment (Vault Helm chart).
  - Kong Gateway installation with rate-limiting & JWT auth plugins.

- **Phase 4: LangGraph Agent Core & SOLID Adapter**
  - Develop Python/TypeScript LangGraph agent with state checkpointer.
  - Implement `ILLMProviderAdapter` for Google Gemini 2.0 Flash & AWS Bedrock.

- **Phase 5: React + CopilotKit UI Integration**
  - Lightweight React application with CopilotKit hooks talking to Kong Gateway.
