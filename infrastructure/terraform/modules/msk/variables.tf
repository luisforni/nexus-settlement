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
  description = "Private subnet IDs for MSK brokers. Must have at least num_brokers entries."
  type        = list(string)
}

variable "allowed_cidr_blocks" {
  description = "CIDR blocks allowed to reach Kafka ports."
  type        = list(string)
}

variable "kafka_version" {
  description = "Apache Kafka version for the MSK cluster."
  type        = string
  default     = "3.6.0"
}

variable "broker_instance_type" {
  description = "MSK broker instance type."
  type        = string
  default     = "kafka.t3.small"
}

variable "num_brokers" {
  description = "Number of broker nodes (1 for local; must be a multiple of AZs in production)."
  type        = number
  default     = 1
}

variable "topics" {
  description = "List of Kafka topics to create."
  type = list(object({
    name               = string
    partitions         = number
    replication_factor = number
  }))
  default = []
}

variable "compose_working_dir" {
  description = "Absolute path to the docker-compose project root (used by the topic provisioner)."
  type        = string
  default     = "."
}
