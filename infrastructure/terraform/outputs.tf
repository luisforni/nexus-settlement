# ── Network ───────────────────────────────────────────────────────────────────
output "vpc_id" {
  description = "VPC ID"
  value       = module.vpc.vpc_id
}

output "private_subnet_ids" {
  description = "Private subnet IDs (used by RDS, ElastiCache, MSK)"
  value       = module.vpc.private_subnet_ids
}

output "public_subnet_ids" {
  description = "Public subnet IDs (used by load balancers / bastion)"
  value       = module.vpc.public_subnet_ids
}

# ── Database ──────────────────────────────────────────────────────────────────
output "rds_endpoint" {
  description = "RDS instance endpoint (host:port)"
  value       = module.rds.endpoint
}

output "rds_port" {
  description = "RDS port"
  value       = module.rds.port
}

output "rds_db_name" {
  description = "Database name"
  value       = module.rds.db_name
}

# ── Cache ─────────────────────────────────────────────────────────────────────
output "redis_primary_endpoint" {
  description = "ElastiCache primary endpoint"
  value       = module.elasticache.primary_endpoint
}

output "redis_port" {
  description = "ElastiCache port"
  value       = module.elasticache.port
}

# ── Streaming ─────────────────────────────────────────────────────────────────
output "msk_bootstrap_brokers" {
  description = "MSK bootstrap broker connection string"
  value       = module.msk.bootstrap_brokers
}

output "msk_cluster_arn" {
  description = "MSK cluster ARN"
  value       = module.msk.cluster_arn
}
