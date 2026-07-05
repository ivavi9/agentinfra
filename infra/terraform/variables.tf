variable "aws_region" {
  type        = string
  description = "The target AWS Region"
  default     = "us-east-1"
}

variable "aws_profile" {
  type        = string
  description = "The AWS SSO Profile name"
  default     = "agent-dev"
}

variable "cluster_name" {
  type        = string
  description = "The EKS Cluster Name"
  default     = "agent-infra-cluster"
}

variable "vpc_cidr" {
  type        = string
  description = "The VPC CIDR block"
  default     = "10.0.0.0/16"
}
