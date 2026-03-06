# ── General ───────────────────────────────────────────────────────────────────
variable "project" {
  description = "Project name used as a prefix for all resource names."
  type        = string
  default     = "nexus-settlement"
}

variable "environment" {
  description = "Deployment environment (local | staging | production)."
  type        = string
  default     = "local"
  validation {
    condition     = contains(["local", "staging", "production"], var.environment)
    error_message = "environment must be one of: local, staging, production."
  }
}

variable "aws_region" {
  description = "AWS region (or LocalStack target region)."
  type        = string
  default     = "us-east-1"
}

variable "localstack_endpoint" {
  description = "LocalStack gateway URL. Remove this variable when targeting real AWS."
  type        = string
  default     = "http://localhost:4566"
}

# ── Networking ────────────────────────────────────────────────────────────────
variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.0.0.0/16"
}

# ── Database (RDS PostgreSQL) ─────────────────────────────────────────────────
variable "db_name" {
  description = "PostgreSQL database name."
  type        = string
  default     = "nexus_settlement"
}

variable "db_username" {
  description = "PostgreSQL master username."
  type        = string
  default     = "nexus_user"
}

variable "db_password" {
  description = "PostgreSQL master password. Supply via TF_VAR_db_password or tfvars file."
  type        = string
  sensitive   = true
}

variable "rds_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t3.micro"
}

variable "rds_allocated_storage" {
  description = "RDS allocated storage in GB."
  type        = number
  default     = 20
}

# ── Cache (ElastiCache Redis) ─────────────────────────────────────────────────
variable "redis_auth_token" {
  description = "Redis AUTH token. Supply via TF_VAR_redis_auth_token or tfvars file."
  type        = string
  sensitive   = true
}

variable "elasticache_node_type" {
  description = "ElastiCache node type."
  type        = string
  default     = "cache.t3.micro"
}

variable "elasticache_num_replicas" {
  description = "Number of Redis read replicas (0 = single-node, sufficient for local)."
  type        = number
  default     = 0
}

# ── Streaming (MSK Kafka) ─────────────────────────────────────────────────────
variable "msk_broker_instance_type" {
  description = "MSK broker instance type."
  type        = string
  default     = "kafka.t3.small"
}

variable "msk_num_brokers" {
  description = "Number of Kafka brokers (1 for local; ≥3 for production)."
  type        = number
  default     = 1
}

variable "kafka_topics" {
  description = "Kafka topics to provision on the MSK cluster."
  type = list(object({
    name               = string
    partitions         = number
    replication_factor = number
  }))
  default = [
    { name = "nexus.settlements",     partitions = 3, replication_factor = 1 },
    { name = "nexus.fraud.alerts",    partitions = 3, replication_factor = 1 },
    { name = "nexus.notifications",   partitions = 3, replication_factor = 1 },
    { name = "nexus.settlements.dlq", partitions = 1, replication_factor = 1 },
    { name = "nexus.fraud.dlq",       partitions = 1, replication_factor = 1 },
  ]
}
