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
  description = "Private subnet IDs for the DB subnet group (≥2 AZs recommended)."
  type        = list(string)
}

variable "allowed_cidr_blocks" {
  description = "CIDR blocks allowed to reach port 5432."
  type        = list(string)
}

variable "db_name" {
  description = "Name of the initial database."
  type        = string
}

variable "db_username" {
  description = "Master DB username."
  type        = string
}

variable "db_password" {
  description = "Master DB password."
  type        = string
  sensitive   = true
}

variable "instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t3.micro"
}

variable "allocated_storage" {
  description = "Allocated storage in GB."
  type        = number
  default     = 20
}

variable "engine_version" {
  description = "PostgreSQL engine version."
  type        = string
  default     = "16.2"
}
