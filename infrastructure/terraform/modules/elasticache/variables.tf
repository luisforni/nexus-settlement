variable "project" {
  description = "Project name."
  type        = string
}

variable "environment" {
  description = "Deployment environment."
  type        = string
}

variable "vpc_id" {
  description = "VPC in which to create the security group."
  type        = string
}

variable "subnet_ids" {
  description = "Private subnet IDs for the ElastiCache subnet group (≥2 AZs recommended)."
  type        = list(string)
}

variable "allowed_cidr_blocks" {
  description = "CIDR blocks allowed to reach port 6379."
  type        = list(string)
}

variable "auth_token" {
  description = "Redis AUTH token (password). Must be 16–128 characters."
  type        = string
  sensitive   = true
}

variable "node_type" {
  description = "ElastiCache node type."
  type        = string
  default     = "cache.t3.micro"
}

variable "num_replicas" {
  description = "Number of read replicas (0 = single-node for local simulation)."
  type        = number
  default     = 0
}
