# System Invariants

## 1. Budget & Resource Constraints
- **Credit / Budget Boundary**: Maximum initial budget is $160 - $180 AWS credits / Free Tier.
- **Cost Minimization**: Avoid always-on expensive managed resources where serverless, lightweight (k3s on EC2), or micro-cluster alternatives exist.
- **EKS Cost Awareness**: AWS EKS control plane costs ~$0.10/hour (~$72/month) plus worker node (EC2) instance costs. Need strict evaluation against k3s on EC2 for max runway.

## 2. Architectural & SOLID Principles
- **SOLID Principles in AI**:
  - *SRP*: Strict separation between UI (CopilotKit), Security/AI Gateway (Kong), Secrets (Vault), Agent Core (LangGraph), and Model Adapters.
  - *OCP*: Extend agent tools and add new LLMs in AI Gateway without modifying graph runner.
  - *LSP*: Google Gemini and AWS Bedrock models conform to unified OpenAI-compatible interface exposed by AI Gateway.
  - *ISP*: Decoupled micro-interfaces for secrets, tools, checkpointers, and AI Gateway clients.
  - *DIP*: LangGraph workflows depend on abstractions (`IAIGatewayClient`), not SDK implementations.
- **Stateful Persistence**: LangGraph graph state checkpointer records state transitions for session resume and auditability.

## 3. AI Gateway & Multi-LLM Routing Strategy
- **Dual-Model Gateway Routing**: All LLM traffic (Google Gemini 2.0 Flash & AWS Bedrock Nova/Claude) is routed through Kong AI Gateway / LiteLLM Proxy via unified OpenAI-compatible endpoint.
- **Automatic Model Failover**: AI Gateway automatically fails over between Bedrock and Gemini in case of rate limits (HTTP 429) or provider outages.
- **Semantic Prompt Caching & Token Rate-Limiting**: Gateway handles local caching and global token quotas to protect LLM budget.

## 4. Production Readiness & Security Governance
- **Zero Secret Leakage to Frontend**: The React UI never handles or stores backend LLM API keys or Vault tokens. All client calls use short-lived user JWTs.
- **Production Data Isolation & RBAC**: Multi-tenant isolation enforced via JWT claims and PostgreSQL Row-Level Security in the checkpointer.
- **Zero Trust Edge**: All traffic must pass through Kong Firewall / API Gateway (TLS 1.3, Auth, WAF, Rate Limit, CORS).
- **Secrets Lifecycle**: Secrets managed strictly by HashiCorp Vault. No hardcoded credentials.
- **Least Privilege (PoLP)**: AWS IAM Roles for Service Accounts (IRSA) and Vault K8s auth for fine-grained permissions.
