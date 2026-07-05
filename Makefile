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

.PHONY: help bootstrap teardown config-check clean

help:
	@echo "Agent Infrastructure Ephemeral Environment CLI Helper"
	@echo "====================================================="
	@echo "Available commands:"
	@echo "  make bootstrap   - Spin up EKS & VPC network via Terraform and generate local kubeconfig"
	@echo "  make teardown    - Completely destroy EKS, VPC network, and clear local kubeconfig"
	@echo "  make clean       - Remove local temporary files, caches, and configuration directories"

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
	@echo "==> You can now interact with the cluster using: KUBECONFIG=$(KUBECONFIG_PATH) kubectl get nodes"

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

clean:
	@echo "==> Cleaning up local state caches..."
	rm -rf .kube/
	rm -f $(TERRAFORM_DIR)/*.tfstate*
	rm -rf $(TERRAFORM_DIR)/.terraform/
	rm -f $(TERRAFORM_DIR)/.terraform.lock.hcl
