# Configuration Variables
TERRAFORM_DIR=infra/terraform
PROFILE=agent-dev
REGION=us-east-1
CLUSTER_NAME=agent-infra-cluster
KUBECONFIG_PATH=$(shell pwd)/.kube/config

# Executables
AWS_CLI=/opt/homebrew/bin/aws
TERRAFORM=/opt/homebrew/bin/terraform
KUBECTL=/opt/homebrew/bin/kubectl
HELM=/opt/homebrew/bin/helm

.PHONY: help bootstrap deploy-security write-secret configure-vault-auth build-and-push deploy-agent teardown config-check clean

help:
	@echo "Agent Infrastructure Ephemeral Environment CLI Helper"
	@echo "====================================================="
	@echo "Available commands:"
	@echo "  make bootstrap            - Spin up EKS & VPC network via Terraform and generate local kubeconfig"
	@echo "  make deploy-security      - Deploy Vault and Kong API Gateway via Helm inside the cluster"
	@echo "  make write-secret         - Securely prompt and write Google Gemini API Key to Vault"
	@echo "  make configure-vault-auth - Configure Vault Kubernetes authentication and policy mappings"
	@echo "  make build-and-push       - Build Docker container and push to private ECR repository"
	@echo "  make deploy-agent         - Deploy ServiceAccount and LangGraph agent core pods to EKS"
	@echo "  make teardown             - Completely destroy EKS, VPC network, and clear local kubeconfig"
	@echo "  make clean                - Remove local temporary files, caches, and configuration directories"

bootstrap: config-check
	@echo "==> Initializing Terraform..."
	cd $(TERRAFORM_DIR) && $(TERRAFORM) init
	@echo "==> Provisioning AWS Infrastructure (this will take 15-20 minutes)..."
	cd $(TERRAFORM_DIR) && $(TERRAFORM) apply -auto-approve \
		-var="aws_profile=$(PROFILE)" \
		-var="aws_region=$(REGION)" \
		-var="cluster_name=$(CLUSTER_NAME)"
	@echo "==> Configuring local Kubernetes context (kubeconfig)..."
	mkdir -p $(shell dirname $(KUBECONFIG_PATH))
	$(AWS_CLI) eks update-kubeconfig \
		--name $(CLUSTER_NAME) \
		--region $(REGION) \
		--profile $(PROFILE) \
		--kubeconfig $(KUBECONFIG_PATH)
	@echo "==> EKS Cluster bootstrap complete!"
	@echo "==> Run 'make deploy-security' next to install Vault and Kong Gateway."

deploy-security: config-check
	@echo "==> Adding Helm repositories..."
	KUBECONFIG=$(KUBECONFIG_PATH) $(HELM) repo add hashicorp https://helm.releases.hashicorp.com
	KUBECONFIG=$(KUBECONFIG_PATH) $(HELM) repo add kong https://charts.konghq.com
	KUBECONFIG=$(KUBECONFIG_PATH) $(HELM) repo update
	@echo "==> Deploying HashiCorp Vault (Dev Mode)..."
	KUBECONFIG=$(KUBECONFIG_PATH) $(HELM) upgrade --install vault hashicorp/vault \
		--values infra/helm/vault-values.yaml
	@echo "==> Deploying Kong Gateway (DB-less)..."
	KUBECONFIG=$(KUBECONFIG_PATH) $(HELM) upgrade --install kong kong/kong \
		--values infra/helm/kong-values.yaml
	@echo "==> Applying Kong rate-limiting and CORS policies..."
	KUBECONFIG=$(KUBECONFIG_PATH) $(KUBECTL) apply -f infra/k8s/kong-plugins.yaml
	@echo "==> Waiting for Vault pod to be Ready..."
	KUBECONFIG=$(KUBECONFIG_PATH) $(KUBECTL) wait --for=condition=Ready pod/vault-0 --timeout=120s
	@echo "==> Bootstrapping Vault KV engine..."
	KUBECONFIG=$(KUBECONFIG_PATH) $(KUBECTL) exec -it vault-0 -- sh -c \
		"VAULT_TOKEN=root-vault-token vault secrets enable -path=secret kv-v2" || true
	@echo "==> Security layer deployed successfully!"
	@echo "==> Run 'make write-secret' next to write your Gemini API key securely."

write-secret: config-check
	@read -p "Enter Google Gemini API Key (input will be hidden): " -s key; \
	echo ""; \
	if [ -z "$$key" ]; then \
		echo "ERROR: API key cannot be empty"; \
		exit 1; \
	fi; \
	echo "==> Writing key to Vault kv/data/secret/gemini..."; \
	KUBECONFIG=$(KUBECONFIG_PATH) $(KUBECTL) exec -i vault-0 -- sh -c \
		"VAULT_TOKEN=root-vault-token vault kv put secret/gemini api_key=$$key"; \
	echo "==> Generating Kong AI Gateway secret config..."; \
	KUBECONFIG=$(KUBECONFIG_PATH) $(KUBECTL) create secret generic gemini-ai-proxy-config \
		--from-literal=config="{\"route_type\": \"llm/v1/chat\", \"auth\": {\"allow_override\": false, \"header_name\": \"Authorization\", \"header_value\": \"Bearer $$key\"}, \"model\": {\"provider\": \"openai\", \"name\": \"gemini-2.5-flash\", \"options\": {\"upstream_url\": \"https://generativelanguage.googleapis.com/v1beta/openai\"}}}" \
		--dry-run=client -o yaml | KUBECONFIG=$(KUBECONFIG_PATH) $(KUBECTL) apply -f -

# ECR URL target (resolves from outputs or default)
ECR_URL=818593257879.dkr.ecr.us-east-1.amazonaws.com/agent-core

configure-vault-auth: config-check
	@echo "==> Enabling Kubernetes authentication in Vault..."
	KUBECONFIG=$(KUBECONFIG_PATH) $(KUBECTL) exec -it vault-0 -- sh -c \
		"VAULT_TOKEN=root-vault-token vault auth enable kubernetes" || true
	@echo "==> Configuring Kubernetes API host mapping in Vault..."
	KUBECONFIG=$(KUBECONFIG_PATH) $(KUBECTL) exec -it vault-0 -- sh -c \
		"VAULT_TOKEN=root-vault-token vault write auth/kubernetes/config kubernetes_host=\"https://kubernetes.default.svc.cluster.local:443\""
	@echo "==> Creating Vault read-only policy for Gemini secrets..."
	KUBECONFIG=$(KUBECONFIG_PATH) $(KUBECTL) exec -i vault-0 -- sh -c \
		"echo 'path \"secret/data/gemini\" { capabilities = [\"read\"] }' | VAULT_TOKEN=root-vault-token vault policy write agent-policy -"
	@echo "==> Registering Vault authorization role for agent ServiceAccount..."
	KUBECONFIG=$(KUBECONFIG_PATH) $(KUBECTL) exec -it vault-0 -- sh -c \
		"VAULT_TOKEN=root-vault-token vault write auth/kubernetes/role/agent-role bound_service_account_names=agent-core-sa bound_service_account_namespaces=default policies=agent-policy ttl=24h"

build-and-push: config-check
	@echo "==> Logging in to AWS ECR..."
	$(AWS_CLI) ecr get-login-password --region $(REGION) --profile $(PROFILE) | docker login --username AWS --password-stdin $(ECR_URL)
	@echo "==> Building agent core Docker container image..."
	docker build --pull --no-cache --platform linux/amd64 -t $(ECR_URL):latest ./app
	@echo "==> Pushing image to private ECR repository..."
	docker push $(ECR_URL):latest

deploy-agent: config-check
	@echo "==> Deploying agent ServiceAccount and permissions..."
	KUBECONFIG=$(KUBECONFIG_PATH) $(KUBECTL) apply -f infra/k8s/agent-auth.yaml
	@echo "==> Deploying agent pods and services..."
	KUBECONFIG=$(KUBECONFIG_PATH) $(KUBECTL) apply -f infra/k8s/agent-deployment.yaml
	@echo "==> Waiting for agent pod to start..."
	KUBECONFIG=$(KUBECONFIG_PATH) $(KUBECTL) rollout status deployment/agent-core --timeout=120s
	@echo "==> Agent core deployed successfully!"


teardown: config-check
	@echo "==> Destroying AWS Infrastructure (this will take 10-15 minutes)..."
	cd $(TERRAFORM_DIR) && $(TERRAFORM) destroy -auto-approve \
		-var="aws_profile=$(PROFILE)" \
		-var="aws_region=$(REGION)" \
		-var="cluster_name=$(CLUSTER_NAME)"
	@echo "==> Infrastructure teardown complete!"
	$(MAKE) clean

config-check:
	@if [ ! -f $(AWS_CLI) ]; then \
		echo "ERROR: AWS CLI not found at $(AWS_CLI)"; \
		exit 1; \
	fi
	@if [ ! -f $(TERRAFORM) ]; then \
		echo "ERROR: Terraform not found at $(TERRAFORM)"; \
		exit 1; \
	fi
	@if [ ! -f $(HELM) ]; then \
		echo "ERROR: Helm not found at $(HELM)"; \
		exit 1; \
	fi
	@if [ ! -f $(KUBECTL) ]; then \
		echo "ERROR: Kubectl not found at $(KUBECTL)"; \
		exit 1; \
	fi

clean:
	@echo "==> Cleaning up local state caches..."
	rm -rf .kube/
	rm -f $(TERRAFORM_DIR)/*.tfstate*
	rm -rf $(TERRAFORM_DIR)/.terraform/
	rm -f $(TERRAFORM_DIR)/.terraform.lock.hcl
