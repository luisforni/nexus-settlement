output "primary_endpoint" {
  description = "Primary endpoint address for the Redis replication group"
  value       = aws_elasticache_replication_group.this.primary_endpoint_address
}

output "port" {
  description = "Redis port"
  value       = 6379
}

output "replication_group_id" {
  description = "ElastiCache replication group ID"
  value       = aws_elasticache_replication_group.this.id
}
