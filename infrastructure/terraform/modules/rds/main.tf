locals {
  name = "${var.project}-${var.environment}"
  common_tags = {
    Project     = var.project
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ── Security Group ────────────────────────────────────────────────────────────
resource "aws_security_group" "rds" {
  name        = "${local.name}-rds-sg"
  description = "Allow PostgreSQL inbound from within the VPC only"
  vpc_id      = var.vpc_id

  ingress {
    description = "PostgreSQL from VPC"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = var.allowed_cidr_blocks
  }

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, { Name = "${local.name}-rds-sg" })
}

# ── DB Subnet Group ───────────────────────────────────────────────────────────
resource "aws_db_subnet_group" "this" {
  name       = "${local.name}-db-subnet-group"
  subnet_ids = var.subnet_ids

  tags = merge(local.common_tags, { Name = "${local.name}-db-subnet-group" })
}

# ── RDS Instance ──────────────────────────────────────────────────────────────
resource "aws_db_instance" "this" {
  identifier = "${local.name}-postgres"

  engine         = "postgres"
  engine_version = var.engine_version
  instance_class = var.instance_class

  allocated_storage = var.allocated_storage
  storage_type      = "gp3"
  storage_encrypted = true

  db_name  = var.db_name
  username = var.db_username
  password = var.db_password

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false

  # Automated backups
  backup_retention_period = 7
  backup_window           = "03:00-04:00"
  maintenance_window      = "Mon:04:00-Mon:05:00"

  # Disable deletion protection in local simulation so `tf-destroy` works cleanly.
  # Set to true in staging / production.
  deletion_protection = false
  skip_final_snapshot = true

  tags = merge(local.common_tags, { Name = "${local.name}-postgres" })
}
