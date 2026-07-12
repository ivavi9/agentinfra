output "cluster_name" {
  value       = aws_eks_cluster.main.name
  description = "The name of the EKS cluster"
}

output "cluster_endpoint" {
  value       = aws_eks_cluster.main.endpoint
  description = "The endpoint URL for the EKS cluster API"
}

output "cluster_security_group_id" {
  value       = aws_eks_cluster.main.vpc_config[0].cluster_security_group_id
  description = "The security group ID attached to the cluster control plane"
}

output "oidc_provider_arn" {
  value       = aws_iam_openid_connect_provider.eks.arn
  description = "The ARN of the OIDC identity provider linked to EKS"
}

output "vpc_id" {
  value       = aws_vpc.main.id
  description = "The ID of the created VPC"
}

output "ecr_repository_url" {
  value       = aws_ecr_repository.agent.repository_url
  description = "The URL of the created ECR repository"
}

output "bedrock_access_key_id" {
  value     = aws_iam_access_key.bedrock_user_key.id
  sensitive = true
}

output "bedrock_secret_access_key" {
  value     = aws_iam_access_key.bedrock_user_key.secret
  sensitive = true
}

output "rds_endpoint" {
  value       = aws_db_instance.postgres.endpoint
  description = "The connection endpoint for the RDS PostgreSQL checkpointer"
}

output "rds_db_name" {
  value       = aws_db_instance.postgres.db_name
  description = "The name of the initialized checkpointer database"
}

output "rds_username" {
  value       = aws_db_instance.postgres.username
  description = "The admin username for RDS database access"
}

output "rds_password" {
  value       = aws_db_instance.postgres.password
  sensitive   = true
  description = "The admin password for RDS database access"
}

output "cognito_user_pool_id" {
  value       = aws_cognito_user_pool.user_pool.id
  description = "The AWS Cognito User Pool ID"
}

output "cognito_client_id" {
  value       = aws_cognito_user_pool_client.client.id
  description = "The AWS Cognito Client Application ID"
}

output "cognito_endpoint" {
  value       = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.user_pool.id}"
  description = "The issuer endpoint URL for Cognito JWT token validation"
}
