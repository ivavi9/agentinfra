# Configuration Variables
TERRAFORM_DIR=infra/terraform
PROFILE=agent-dev
REGION=us-east-1
CLUSTER_NAME=agent-infra-cluster
KUBECONFIG_PATH=$(shell pwd)/.kube/config

# Vault dev-mode root token — override via: make deploy-security VAULT_DEV_TOKEN=mytoken
# This is a dev-only bootstrap token; it has no value outside the ephemeral cluster.
VAULT_DEV_TOKEN ?= root-vault-token

# Executables
AWS_CLI=/opt/homebrew/bin/aws
TERRAFORM=/opt/homebrew/bin/terraform
KUBECTL=/opt/homebrew/bin/kubectl
HELM=/opt/homebrew/bin/helm
DOCKER=DOCKER_HOST=unix://$(HOME)/.colima/default/docker.sock /opt/homebrew/bin/docker

.PHONY: help bootstrap deploy-security write-secret configure-vault-auth configure-bedrock-auth build-and-push deploy-agent pre-teardown purge-orphans teardown config-check clean

help:
	@echo "Agent Infrastructure Ephemeral Environment CLI Helper"
	@echo "====================================================="
	@echo "Available commands:"
	@echo "  make bootstrap               - Spin up EKS & VPC network via Terraform and generate local kubeconfig"
	@echo "  make deploy-security         - Deploy Vault and Kong API Gateway via Helm inside the cluster"
	@echo "  make write-secret            - Securely prompt and write Google Gemini API Key to Vault"
	@echo "  make configure-vault-auth    - Configure Vault Kubernetes authentication and policy mappings"
	@echo "  make configure-bedrock-auth  - Configure Kong Gateway AI Proxy for AWS Bedrock integration"
	@echo "  make build-and-push          - Build Docker container and push to private ECR repository"
	@echo "  make deploy-agent            - Deploy ServiceAccount and LangGraph agent core pods to EKS"
	@echo "  make pre-teardown         - Drain k8s LoadBalancer Services so AWS removes ELBs before Terraform runs"
	@echo "  make purge-orphans        - Force-delete any leftover ELBs, ENIs, SGs blocking the cluster VPC"
	@echo "  make teardown             - Safe full teardown: pre-teardown → purge-orphans → terraform destroy → clean"
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
	@echo "==> Deploying AI Gateway Ingress rules..."
	KUBECONFIG=$(KUBECONFIG_PATH) $(KUBECTL) apply -f infra/k8s/ai-gateway.yaml
	@echo "==> Waiting for Vault pod to be Ready..."
	KUBECONFIG=$(KUBECONFIG_PATH) $(KUBECTL) wait --for=condition=Ready pod/vault-0 --timeout=120s
	@echo "==> Bootstrapping Vault KV engine..."
	KUBECONFIG=$(KUBECONFIG_PATH) $(KUBECTL) exec -it vault-0 -- sh -c \
		"VAULT_TOKEN=$(VAULT_DEV_TOKEN) vault secrets enable -path=secret kv-v2" || true
	@echo "==> Security layer deployed successfully!"
	@echo "==> Run 'make write-secret' next to write your Gemini API key securely."

write-secret: config-check
	@read -p "Enter Google Gemini API Key (input will be hidden): " -s key; \
	echo ""; \
	if [ -z "$$key" ]; then \
		echo "ERROR: API key cannot be empty"; \
		exit 1; \
	fi; \
	db_pass=$$(cd $(TERRAFORM_DIR) && $(TERRAFORM) output -raw rds_password); \
	db_host=$$(cd $(TERRAFORM_DIR) && $(TERRAFORM) output -raw rds_endpoint | cut -d: -f1); \
	db_name=$$(cd $(TERRAFORM_DIR) && $(TERRAFORM) output -raw rds_db_name); \
	db_user=$$(cd $(TERRAFORM_DIR) && $(TERRAFORM) output -raw rds_username); \
	pool_id=$$(cd $(TERRAFORM_DIR) && $(TERRAFORM) output -raw cognito_user_pool_id); \
	client_id=$$(cd $(TERRAFORM_DIR) && $(TERRAFORM) output -raw cognito_client_id); \
	cognito_ep=$$(cd $(TERRAFORM_DIR) && $(TERRAFORM) output -raw cognito_endpoint); \
	echo "==> Writing secrets to Vault kv/data/secret/gemini..."; \
	KUBECONFIG=$(KUBECONFIG_PATH) $(KUBECTL) exec -i vault-0 -- sh -c \
		"VAULT_TOKEN=$(VAULT_DEV_TOKEN) vault kv put secret/gemini api_key=$$key db_password=$$db_pass db_host=$$db_host db_name=$$db_name db_user=$$db_user db_port=5432 cognito_user_pool_id=$$pool_id cognito_client_id=$$client_id cognito_endpoint=$$cognito_ep aws_region=$(REGION)"; \
	echo "==> Generating Kong AI Gateway secret config..."; \
	KUBECONFIG=$(KUBECONFIG_PATH) $(KUBECTL) create secret generic gemini-ai-proxy-config \
		--from-literal=config="{\"route_type\": \"llm/v1/chat\", \"auth\": {\"allow_override\": false, \"header_name\": \"Authorization\", \"header_value\": \"Bearer $$key\"}, \"model\": {\"provider\": \"openai\", \"name\": \"gemini-2.5-flash\", \"options\": {\"upstream_url\": \"https://generativelanguage.googleapis.com/v1beta/openai\"}}}" \
		--dry-run=client -o yaml | KUBECONFIG=$(KUBECONFIG_PATH) $(KUBECTL) apply -f -

# ECR URL target (resolves from outputs or default)
ECR_URL=818593257879.dkr.ecr.us-east-1.amazonaws.com/agent-core

configure-vault-auth: config-check
	@echo "==> Enabling Kubernetes authentication in Vault..."
	KUBECONFIG=$(KUBECONFIG_PATH) $(KUBECTL) exec -it vault-0 -- sh -c \
		"VAULT_TOKEN=$(VAULT_DEV_TOKEN) vault auth enable kubernetes" || true
	@echo "==> Configuring Kubernetes API host mapping in Vault..."
	KUBECONFIG=$(KUBECONFIG_PATH) $(KUBECTL) exec -it vault-0 -- sh -c \
		"VAULT_TOKEN=$(VAULT_DEV_TOKEN) vault write auth/kubernetes/config kubernetes_host=\"https://kubernetes.default.svc.cluster.local:443\""
	@echo "==> Creating Vault read-only policy for Gemini secrets..."
	KUBECONFIG=$(KUBECONFIG_PATH) $(KUBECTL) exec -i vault-0 -- sh -c \
		"echo 'path \"secret/data/gemini\" { capabilities = [\"read\"] }' | VAULT_TOKEN=$(VAULT_DEV_TOKEN) vault policy write agent-policy -"
	@echo "==> Registering Vault authorization role for agent ServiceAccount..."
	KUBECONFIG=$(KUBECONFIG_PATH) $(KUBECTL) exec -it vault-0 -- sh -c \
		"VAULT_TOKEN=$(VAULT_DEV_TOKEN) vault write auth/kubernetes/role/agent-role bound_service_account_names=agent-core-sa bound_service_account_namespaces=default policies=agent-policy ttl=24h"

configure-bedrock-auth: config-check
	@echo "==> Generating keyless Kong Bedrock secret configuration (IMDS node role)..."
	KUBECONFIG=$(KUBECONFIG_PATH) $(KUBECTL) create secret generic gemini-ai-proxy-config \
		--from-literal=config="{\"route_type\": \"llm/v1/chat\", \"auth\": {\"allow_override\": false}, \"model\": {\"provider\": \"bedrock\", \"name\": \"us.amazon.nova-lite-v1:0\", \"options\": {\"bedrock\": {\"aws_region\": \"$(REGION)\"}}}}" \
		--dry-run=client -o yaml | KUBECONFIG=$(KUBECONFIG_PATH) $(KUBECTL) apply -f -

upload-samples: config-check
	@echo "==> Fetching landing S3 bucket name from Terraform..."
	@bucket=$$(cd $(TERRAFORM_DIR) && $(TERRAFORM) output -raw landing_bucket_name); \
	if [ -z "$$bucket" ] || [ "$$bucket" = "No outputs found" ]; then \
		echo "ERROR: Failed to retrieve S3 landing bucket name from Terraform outputs"; \
		exit 1; \
	fi; \
	echo "==> Copying sample JSON data to S3 bucket $$bucket..."; \
	$(AWS_CLI) s3 cp scratch/samples/customer.json s3://$$bucket/raw/customer/customer.json --profile $(PROFILE); \
	$(AWS_CLI) s3 cp scratch/samples/transaction.json s3://$$bucket/raw/transaction/transaction.json --profile $(PROFILE); \
	echo "==> Raw landing zone sample assets uploaded successfully!"

build-and-push: config-check
	@echo "==> Logging in to AWS ECR..."
	$(AWS_CLI) ecr get-login-password --region $(REGION) --profile $(PROFILE) | $(DOCKER) login --username AWS --password-stdin $(ECR_URL)
	@echo "==> Building agent core Docker container image..."
	$(DOCKER) build --pull --platform linux/amd64 -t $(ECR_URL):latest ./app
	@echo "==> Pushing image to private ECR repository..."
	$(DOCKER) push $(ECR_URL):latest

deploy-agent: config-check
	@echo "==> Deploying agent ServiceAccount and permissions..."
	KUBECONFIG=$(KUBECONFIG_PATH) $(KUBECTL) apply -f infra/k8s/agent-auth.yaml
	@echo "==> Deploying agent pods and services..."
	KUBECONFIG=$(KUBECONFIG_PATH) $(KUBECTL) apply -f infra/k8s/agent-deployment.yaml
	@echo "==> Waiting for agent pod to start..."
	KUBECONFIG=$(KUBECONFIG_PATH) $(KUBECTL) rollout status deployment/agent-core --timeout=120s
	@echo "==> Agent core deployed successfully!"


# ---------------------------------------------------------------------------
# pre-teardown: Gracefully remove Kubernetes-managed cloud resources (ELBs)
# before Terraform runs, so AWS doesn't leave orphaned dependencies.
# Safe to run even if kubeconfig is missing — steps degrade gracefully.
# ---------------------------------------------------------------------------
pre-teardown:
	@echo "==> [1/3] Draining Kubernetes LoadBalancer Services (graceful ELB removal)..."
	@if [ -f $(KUBECONFIG_PATH) ]; then \
		LB_SVCS=$$(KUBECONFIG=$(KUBECONFIG_PATH) $(KUBECTL) get svc --all-namespaces \
			-o jsonpath='{range .items[?(@.spec.type=="LoadBalancer")]}{.metadata.namespace}/{.metadata.name} {end}' 2>/dev/null); \
		if [ -n "$$LB_SVCS" ]; then \
			echo "  Found LoadBalancer services: $$LB_SVCS"; \
			for svc in $$LB_SVCS; do \
				ns=$$(echo $$svc | cut -d/ -f1); \
				name=$$(echo $$svc | cut -d/ -f2); \
				echo "  ==> Deleting Service $$name in namespace $$ns..."; \
				KUBECONFIG=$(KUBECONFIG_PATH) $(KUBECTL) delete svc $$name -n $$ns --timeout=60s || true; \
			done; \
			echo "  Waiting 30s for AWS to release ELB network interfaces..."; \
			sleep 30; \
		else \
			echo "  No LoadBalancer services found — skipping."; \
		fi; \
	 else \
		echo "  No kubeconfig found — skipping k8s drain (cluster already gone)."; \
	fi
	@echo "==> [1/3] Pre-teardown complete."

# ---------------------------------------------------------------------------
# purge-orphans: Safety-net pass. Finds and deletes any ELBs, orphan
# security groups, or dangling ENIs attached to the cluster VPC that were
# NOT managed by Terraform (created dynamically by the k8s cloud controller).
# ---------------------------------------------------------------------------
purge-orphans: config-check
	@echo "==> [2/3] Scanning for orphaned AWS resources in cluster VPC..."
	@VPC_ID=$$($(AWS_CLI) ec2 describe-vpcs \
			--profile $(PROFILE) --region $(REGION) \
			--filters "Name=tag:Name,Values=$(CLUSTER_NAME)-vpc" \
			--query "Vpcs[0].VpcId" --output text 2>/dev/null); \
	if [ -z "$$VPC_ID" ] || [ "$$VPC_ID" = "None" ]; then \
		echo "  Cluster VPC not found — nothing to purge."; \
	else \
		echo "  Found VPC: $$VPC_ID"; \
		echo "  Deleting orphaned Classic Load Balancers..."; \
		ELBS=$$($(AWS_CLI) elb describe-load-balancers \
			--profile $(PROFILE) --region $(REGION) \
			--query "LoadBalancerDescriptions[?VPCId=='$$VPC_ID'].LoadBalancerName" \
			--output text 2>/dev/null); \
		for elb in $$ELBS; do \
			echo "    ==> Deleting Classic ELB: $$elb"; \
			$(AWS_CLI) elb delete-load-balancer \
				--load-balancer-name $$elb \
				--profile $(PROFILE) --region $(REGION); \
		done; \
		echo "  Deleting orphaned Network Load Balancers..."; \
		NLBS=$$($(AWS_CLI) elbv2 describe-load-balancers \
			--profile $(PROFILE) --region $(REGION) \
			--query "LoadBalancers[?VpcId=='$$VPC_ID'].LoadBalancerArn" \
			--output text 2>/dev/null); \
		for nlb in $$NLBS; do \
			echo "    ==> Deleting NLB: $$nlb"; \
			$(AWS_CLI) elbv2 delete-load-balancer \
				--load-balancer-arn $$nlb \
				--profile $(PROFILE) --region $(REGION); \
		done; \
		if [ -n "$$ELBS" ] || [ -n "$$NLBS" ]; then \
			echo "  Waiting 30s for ELB ENIs to be released by AWS..."; \
			sleep 30; \
		fi; \
		echo "  Deleting orphaned non-default Security Groups..."; \
		SGS=$$($(AWS_CLI) ec2 describe-security-groups \
			--filters "Name=vpc-id,Values=$$VPC_ID" \
			--profile $(PROFILE) --region $(REGION) \
			--query "SecurityGroups[?GroupName!='default'].GroupId" \
			--output text 2>/dev/null); \
		for sg in $$SGS; do \
			echo "    ==> Deleting Security Group: $$sg"; \
			$(AWS_CLI) ec2 delete-security-group \
				--group-id $$sg \
				--profile $(PROFILE) --region $(REGION) || true; \
		done; \
	fi
	@echo "==> [2/3] Orphan purge complete."

# ---------------------------------------------------------------------------
# teardown: Full safe teardown sequence:
#   pre-teardown (k8s drain) → purge-orphans (AWS cleanup) → terraform destroy → local clean
# ---------------------------------------------------------------------------
teardown: config-check pre-teardown purge-orphans
	@echo "==> [3/3] Destroying remaining AWS Infrastructure via Terraform..."
	cd $(TERRAFORM_DIR) && $(TERRAFORM) destroy -auto-approve \
		-var="aws_profile=$(PROFILE)" \
		-var="aws_region=$(REGION)" \
		-var="cluster_name=$(CLUSTER_NAME)"
	@echo "==> Terraform destroy complete."
	$(MAKE) clean
	@echo ""
	@echo "  ✅ Teardown complete — AWS account is clean. No idle costs remaining."

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
