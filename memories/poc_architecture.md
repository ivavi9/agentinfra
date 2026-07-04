# PoC Architecture: Production-Grade Agentic Infrastructure (v1.0)

## Architectural Vision
A secure, scalable, and cost-effective AI Agent infrastructure deployed on AWS/Kubernetes. The system features a React + CopilotKit frontend, Kong API Gateway with **AI Gateway capabilities**, HashiCorp Vault for secrets lifecycle management, and a LangGraph agent runtime adhering strictly to SOLID design principles and enterprise governance standards.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      FRONTEND LAYER (Prod-Grade React)                      │
│  [ Lightweight React UI + CopilotKit Components & Hooks ]                    │
│  ├── TLS 1.3 Encryption, CSP Headers, XSS Prevention                        │
│  ├── User Auth JWT Tokens (No Secrets / API Keys in Browser)                │
│  └── Sanitized Data Rendering & Error Boundaries                            │
└────────────────────────────────────────┬────────────────────────────────────┘
                                         │ HTTPS / WebSockets (TLS Encrypted)
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    SECURITY & AI GATEWAY LAYER (Prod Kong)                  │
│  [ Kong API Gateway & Firewall + AI Gateway Proxy ]                         │
│  ├── WAF Rules, OWASP Protection & IP Filtering                             │
│  ├── JWT Authentication & RBAC Verification                                 │
│  ├── Multi-LLM Unified Endpoint (/v1/chat/completions)                      │
│  ├── Token Rate Limiting, Semantic Caching & Cost Governance                │
│  └── Automatic Model Failover (Bedrock ↔ Gemini)                            │
└────────────────────────────────────────┬────────────────────────────────────┘
                                         │ Internal K8s Network (mTLS)
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                 KUBERNETES BACKEND LAYER (EKS / k3s Prod)                   │
│                                                                             │
│  ┌─────────────────────────────────┐   ┌────────────────────────────────┐  │
│  │ HashiCorp Vault (Production)    │   │ LangGraph Agent Core Pods      │  │
│  │ ├── Stores Gemini API Keys      │◄──┼─ Dynamic Secret Injection      │  │
│  │ └── Stores AWS Bedrock Creds    │   │ └── Unified AI Gateway Adapter │  │
│  └─────────────────────────────────┘   └───────────────┬────────────────┘  │
│                                                        │                   │
│  ┌─────────────────────────────────────────────────────┴────────────────┐  │
│  │ Persistent Production Checkpointer (PostgreSQL + SSL)                 │  │
│  │ └── Thread State History, Audit Trails, Data Isolation per User      │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────┬────────────────────────────────────┘
                                         │ Dual-Model Egress Routing
                                         ├────────────────────────────────────┐
                                         ▼                                    ▼
                              [ AWS Bedrock API ]                   [ Google Gemini API ]
                          (Amazon Nova / Claude Haiku)                (Gemini 2.0 Flash)
```

---

## AI Gateway Integration Pattern (Dual-LLM: Gemini + AWS Bedrock)

### Architectural Overview
By incorporating an **AI Gateway** (Kong AI Gateway plugin / LiteLLM proxy), the LangGraph Agent Core interacts with a single, unified, OpenAI-compatible endpoint. The gateway manages routing, load balancing, secrets resolution from Vault, rate limiting, and failover between Google Gemini and AWS Bedrock.

#### Key Architectural Capabilities of the Dual-LLM AI Gateway:

1. **Unified API Interface (SOLID DIP Principle)**:
   - LangGraph pods issue standard OpenAI-compatible `/v1/chat/completions` payload requests to the AI Gateway.
   - Target models are requested via standardized names: `bedrock/amazon.nova-lite-v1:0` or `gemini/gemini-2.0-flash`.

2. **Automated Multi-Provider Failover**:
   - If AWS Bedrock experiences rate limits (HTTP 429) or regional outages, the AI Gateway automatically retries and fails over to Google Gemini 2.0 Flash seamlessly without failing user sessions.

3. **Semantic Prompt Caching**:
   - Caches frequent agent prompt responses locally (in Redis), drastically reducing latency (from 1.5s down to 20ms) and saving LLM API credits.

4. **Centralized Secrets Lifecycle**:
   - HashiCorp Vault supplies the Google Gemini API Key and AWS Bedrock credentials directly to the AI Gateway layer. LangGraph agent pods do not require model API keys.

5. **Token Quotas & Cost Governance**:
   - Enforces hard token limits (e.g. 50,000 tokens/day per user) across both model providers from one central control plane.

---

## Production Readiness: Ensuring Frontend & Backend Are Production-Grade

When handling and displaying production data in the UI, both layers must satisfy strict production constraints:

### 1. Frontend Production Standards (React + CopilotKit)
* **Zero Secret Leakage**: Browser code never holds LLM API keys or Vault tokens. All requests are authenticated via short-lived user JWT tokens.
* **Content Security Policy (CSP) & XSS Defenses**: Strict headers restricting script execution sources, sanitizing user inputs/agent responses before rendering.
* **Production Build & Asset Optimization**: Minified production build served via CDN/Nginx with Brotli compression and source-map removal.
* **Error Boundaries & Graceful Degradation**: Production error boundaries catch runtime exceptions without displaying raw stack traces.
* **Sanitized Data Display**: Masking sensitive fields (PII, confidential tokens) on the client side before rendering.

### 2. Backend Production Standards (Kong + Vault + LangGraph + K8s)
* **Production State Checkpointer**: LangGraph states are persisted in a production PostgreSQL database with SSL encryption and Row-Level Security (RLS).
* **Production Vault Instance**: Vault operates in HA mode (Raft storage) with TLS enabled, audit logging, and dynamic secret lease rotation.
* **Production Kong Firewall & AI Gateway**: Kong enforcing rate limiting, CORS restrictions, WAF protection, and unified AI model routing.
* **Multi-Tenant Data Isolation**: User ID claims from JWT tokens enforce strict tenant data boundaries in LangGraph checkpointers.
* **High Availability & Auto-Scaling**: Kubernetes HPA scales LangGraph agent pods based on CPU/memory load.
* **Observability & Auditing**: Centralized structured JSON logging, Prometheus metrics, and OpenTelemetry tracing.

---

## SOLID Principles Applied to AI Agent Architecture

1. **Single Responsibility Principle (SRP)**
   - **CopilotKit React UI**: Handles user interactions, state rendering, and streaming UI responses.
   - **Kong Firewall & AI Gateway**: Handles edge security, JWT auth, rate limiting, and unified multi-LLM routing/failover.
   - **HashiCorp Vault**: Manages secret storage, rotation, and access policies.
   - **LangGraph Core**: Manages multi-agent execution graphs, tool execution, and state persistence.
   - **Unified Gateway LLM Client**: Simple HTTP client calling the local AI Gateway endpoint.

2. **Open/Closed Principle (OCP)**
   - Agent graph is open for extension without modifying core runner or gateway routing.
   - New LLM providers (e.g. Anthropic, Mistral) are added in the AI Gateway config without touching LangGraph code.

3. **Liskov Substitution Principle (LSP)**
   - Gemini and Bedrock models implement the same OpenAI-compatible interface exposed by the AI Gateway and are completely interchangeable.

4. **Interface Segregation Principle (ISP)**
   - Small, focused micro-interfaces: `ISecretsResolver`, `IToolExecutor`, `ICheckpointer`, `IAIGatewayClient`.

5. **Dependency Inversion Principle (DIP)**
   - LangGraph nodes depend on abstract `IAIGatewayClient` interfaces, injected at runtime.
