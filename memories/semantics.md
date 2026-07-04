# Semantic Definitions & Domain Terms

## Components & Terminology

- **LangGraph**: Statefulness framework for building complex, multi-agent AI workflows as graphs with state nodes, tools, conditional edges, and checkpoint persistence.
- **React + CopilotKit UI**: Lightweight frontend React application integrating CopilotKit hooks and sidebar/chat components for interactive AI experience.
- **Amazon EKS / k3s**: Container orchestration layer on AWS. EKS = Managed Kubernetes; k3s = Lightweight single-node K8s on EC2 for cost optimization.
- **Kong Gateway / Firewall**: Reverse proxy gateway providing rate limiting, JWT authentication, WAF rules, and route proxying.
- **HashiCorp Vault**: Secrets manager providing dynamic secrets injection, token lifecycle management, and encryption at rest.
- **IRSA (IAM Roles for Service Accounts)**: AWS security mechanism linking Kubernetes ServiceAccounts to AWS IAM roles for fine-grained, temporary credential access.
- **LangGraph Checkpointer**: Persistence engine (e.g. Memory / Postgres / Redis) saving graph state history per thread ID.
- **LLM Provider Adapter**: SOLID abstraction layer enabling seamless swapping between Google Gemini 2.0 Flash and AWS Bedrock models.
