# System Invariants

## 1. Budget & Resource Constraints
- **Credit / Budget Boundary**: Maximum initial budget is $160 - $180 AWS credits / Free Tier.
- **Cost Minimization**: Ephemeral infrastructure deployment mode.
- **EKS Cost Awareness**: Managed EKS control plane costs ~$0.10/hour. To maximize budget runway, the entire infrastructure stack must be created at the start of a development session and completely destroyed at the end.

## 2. Infrastructure Deployment Mode: Ephemeral Sessions
- **Single-Command Provisioning**: Infrastructure (EKS, VPC, nodes) must be fully automated via Terraform / scripts so `make bootstrap` or similar deploys the complete stack.
- **Single-Command Destruction**: All resources must be completely deleted using `make teardown` or similar at the end of every session to prevent lingering charges.
- **Zero Local K8s State Reliance**: No application state (Vault tokens, API endpoints, agent memory threads) should depend on long-lived cluster storage. All code, schemas, and configurations must reside in Git.

## 3. Architectural & SOLID Principles
- **SOLID Principles in AI**:
  - *SRP*: Strict separation between UI (CopilotKit), Security/AI Gateway (Kong), Secrets (Vault), Agent Core (LangGraph), and Model Adapters.
  - *OCP*: Extend agent tools and add new LLMs in AI Gateway without modifying graph runner.
  - *LSP*: Google Gemini and AWS Bedrock models conform to unified OpenAI-compatible interface exposed by AI Gateway.
  - *ISP*: Decoupled micro-interfaces for secrets, tools, checkpointers, and AI Gateway clients.
  - *DIP*: LangGraph workflows depend on abstractions (`IAIGatewayClient`), not SDK implementations.
- **Stateful Persistence**: LangGraph graph state checkpointer records state transitions for session resume and auditability.

## 4. AI Gateway & Multi-LLM Routing Strategy
- **Dual-Model Gateway Routing**: All LLM traffic (Google Gemini 2.0 Flash & AWS Bedrock Nova/Claude) is routed through Kong AI Gateway / LiteLLM Proxy via unified OpenAI-compatible endpoint.
- **Automatic Model Failover**: AI Gateway automatically fails over between Bedrock and Gemini in case of rate limits (HTTP 429) or provider outages.
- **Semantic Prompt Caching & Token Rate-Limiting**: Gateway handles local caching and global token quotas to protect LLM budget.

## 5. Production Readiness & Security Governance
- **Zero Secret Leakage to Frontend**: The React UI never handles or stores backend LLM API keys or Vault tokens. All client calls use short-lived user JWTs.
- **Production Data Isolation & RBAC**: Multi-tenant isolation enforced via JWT claims and PostgreSQL Row-Level Security in the checkpointer.
- **Zero Trust Edge**: All traffic must pass through Kong Firewall / API Gateway (TLS 1.3, Auth, WAF, Rate Limit, CORS).
- **Secrets Lifecycle**: Secrets managed strictly by HashiCorp Vault. No hardcoded credentials.
- **Least Privilege (PoLP)**: AWS IAM Roles for Service Accounts (IRSA) and Vault K8s auth for fine-grained permissions.
