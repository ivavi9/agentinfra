# Antigravity Workspace Rules & Governance

This document outlines workspace-scoped design patterns, behavioral constraints, and developer rules for the AgentInfra project.

## 1. Design & Aesthetic Guidelines
- **Premium Interface Layout**: All frontends must use custom-tailored color palettes (avoid default primary colors), modern fonts (Inter, Outfit), soft drop shadows, card-based grid layouts, and glassmorphism styling.
- **Micro-Animations**: Implement hover states and loading transitions for all buttons and interactive cards.
- **Production Asset Quality**: Do not use blank placeholder elements or plain outlines; use the `generate_image` tool to render working illustrative assets.

## 2. Secrets Management & Keyless Integrity
- **Keyless Architecture**: Always preserve keyless Pod ServiceAccount OIDC identity tokens when connecting to Vault. Under no circumstances should raw API tokens, vault tokens, or passwords be hardcoded or written to files in the repository.
- **AWS Model Permissions**: Route model invocations through Amazon Bedrock using keyless node group policies or secure configSecret credentials.

## 3. Deployment & Environment Governance
- **Architecture Enforcement**: Always compile container images using the `--platform=linux/amd64` flag in Docker to prevent `exec format error` crashes on the cluster node group.
- **Lifecycle Cleanliness**: Ensure the environment can be fully created via `make bootstrap` and completely cleaned up via `make teardown` to avoid AWS idle costs.

## 4. Documentation & State Management
- **State Preservation**: Update `handoff/handoff.md` and `memories/implementation.md` frequently at the end of successful iterations to maintain context between pair programming turns.
- **Clickable Symbol Links**: When referencing code elements, always construct clickable links in the format `[filename](file:///absolute/path/to/file#Lstart-Lend)`.

## 5. Teardown Safety & Lifecycle Cleanliness
- **Always use `make teardown`**: Never run `terraform destroy` directly. The `teardown` Make target chains `pre-teardown → purge-orphans → terraform destroy → clean` in the correct dependency order.
- **Orphaned ELB Pattern**: Kubernetes `LoadBalancer`-type Services cause the cloud controller to dynamically provision AWS Classic/NLBs outside of Terraform state. These become orphans on cluster deletion and block VPC removal with a `DependencyViolation` error.
- **Pre-teardown drain**: Always delete `LoadBalancer` Services via `kubectl` before destroying the cluster, and wait ≥30s for AWS to release the attached ENIs.
- **Post-ELB purge**: After deleting ELBs, always delete their residual Security Groups (named `k8s-elb-*`) before attempting to delete the VPC.
- **AWS SSO Session**: Before running `make teardown`, ensure your SSO session is valid (`aws sso login --profile agent-dev`). Terraform will fail silently on expired credentials.
- **Verification**: After teardown, confirm with `aws eks list-clusters`, `aws ec2 describe-vpcs --filters Name=isDefault,Values=false`, and `aws elb describe-load-balancers` that all resources are empty.

