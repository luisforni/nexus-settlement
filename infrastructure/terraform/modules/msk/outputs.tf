output "bootstrap_brokers" {
  description = "Plaintext bootstrap broker connection string"
  value       = aws_msk_cluster.this.bootstrap_brokers
}

output "bootstrap_brokers_tls" {
  description = "TLS bootstrap broker connection string"
  value       = aws_msk_cluster.this.bootstrap_brokers_tls
}

output "cluster_arn" {
  description = "MSK cluster ARN"
  value       = aws_msk_cluster.this.arn
}

output "cluster_name" {
  description = "MSK cluster name"
  value       = aws_msk_cluster.this.cluster_name
}

output "zookeeper_connect_string" {
  description = "ZooKeeper connection string"
  value       = aws_msk_cluster.this.zookeeper_connect_string
}
