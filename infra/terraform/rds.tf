resource "aws_db_subnet_group" "rds" {
  name       = "${var.cluster_name}-db-subnet-group"
  subnet_ids = aws_subnet.private[*].id

  tags = {
    Name = "${var.cluster_name}-db-subnet-group"
  }
}

resource "aws_security_group" "rds" {
  name        = "${var.cluster_name}-rds-sg"
  description = "Security group for PostgreSQL RDS checkpointer instance"
  vpc_id      = aws_vpc.main.id

  # Allow inbound EKS node requests
  ingress {
    description = "Allow inbound postgres traffic from EKS pods"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  egress {
    from_port        = 0
    to_port          = 0
    protocol         = "-1"
    cidr_blocks      = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }

  tags = {
    Name = "${var.cluster_name}-rds-sg"
  }
}

resource "random_password" "rds_password" {
  length  = 24
  special = false
}

resource "aws_db_instance" "postgres" {
  identifier             = "${var.cluster_name}-db"
  allocated_storage      = 20
  max_allocated_storage  = 100
  engine                 = "postgres"
  engine_version         = "15.7"
  instance_class         = "db.t3.micro"
  db_name                = "agentinfra"
  username               = "postgres"
  password               = random_password.rds_password.result
  db_subnet_group_name   = aws_db_subnet_group.rds.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  skip_final_snapshot    = true
  publicly_accessible    = false

  tags = {
    Name = "${var.cluster_name}-postgres"
  }
}
