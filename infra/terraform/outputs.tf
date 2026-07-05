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
