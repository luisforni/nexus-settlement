locals {
  name = "${var.project}-${var.environment}"
  common_tags = {
    Project     = var.project
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ── Security Group ────────────────────────────────────────────────────────────
resource "aws_security_group" "redis" {
  name        = "${local.name}-redis-sg"
  description = "Allow Redis (6379) inbound from within the VPC only"
  vpc_id      = var.vpc_id

  ingress {
    description = "Redis from VPC"
    from_port   = 6379
    to_port     = 6379
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

  tags = merge(local.common_tags, { Name = "${local.name}-redis-sg" })
}

# ── ElastiCache Subnet Group ──────────────────────────────────────────────────
resource "aws_elasticache_subnet_group" "this" {
  name       = "${local.name}-redis-subnet-group"
  subnet_ids = var.subnet_ids

  tags = merge(local.common_tags, { Name = "${local.name}-redis-subnet-group" })
}

# ── ElastiCache Replication Group (Redis) ─────────────────────────────────────
resource "aws_elasticache_replication_group" "this" {
  replication_group_id = "${local.name}-redis"
  description          = "Redis cluster for ${local.name}"

  engine         = "redis"
  engine_version = "7.1"
  node_type      = var.node_type

  # 1 primary + num_replicas read replicas
  num_cache_clusters = var.num_replicas + 1

  subnet_group_name  = aws_elasticache_subnet_group.this.name
  security_group_ids = [aws_security_group.redis.id]

  # Encryption in-transit and at-rest is mandatory for PCI-DSS environments.
  transit_encryption_enabled = true
  at_rest_encryption_enabled = true
  auth_token                 = var.auth_token

  # Automatic failover and Multi-AZ require at least one read replica.
  automatic_failover_enabled = var.num_replicas > 0 ? true : false
  multi_az_enabled           = var.num_replicas > 0 ? true : false

  tags = merge(local.common_tags, { Name = "${local.name}-redis" })
}
