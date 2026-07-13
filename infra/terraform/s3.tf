# S3 Landing Zone Bucket
resource "random_id" "bucket_id" {
  byte_length = 4
}

resource "aws_s3_bucket" "landing" {
  bucket        = "agent-infra-landing-bucket-${random_id.bucket_id.hex}"
  force_destroy = true

  tags = {
    Name = "agent-infra-landing-bucket"
  }
}

# IAM Policy for S3 access
resource "aws_iam_policy" "s3_access" {
  name        = "agent-infra-s3-access-policy"
  description = "Allows EKS pods to read and write to the landing S3 bucket"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket",
          "s3:DeleteObject"
        ]
        Resource = [
          aws_s3_bucket.landing.arn,
          "${aws_s3_bucket.landing.arn}/*"
        ]
      }
    ]
  })
}

# Attach policy to EKS node role
resource "aws_iam_role_policy_attachment" "node_s3" {
  policy_arn = aws_iam_policy.s3_access.arn
  role       = "agent-infra-cluster-node-role"
}

output "landing_bucket_name" {
  value       = aws_s3_bucket.landing.id
  description = "The name of the created landing S3 bucket"
}
