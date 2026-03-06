terraform {
  required_version = ">= 1.7"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.40"
    }
  }

  # Partial backend configuration — the remaining keys are supplied at init time
  # via an environment-specific .hcl file so that this root module works for
  # both LocalStack (local state) and real AWS (S3 + DynamoDB locking).
  #
  # Local / LocalStack:
  #   terraform init -backend-config=envs/local/backend.hcl
  #
  # Staging:
  #   terraform init -backend-config=envs/staging/backend.hcl -reconfigure
  #
  # Production:
  #   terraform init -backend-config=envs/prod/backend.hcl -reconfigure
  backend "s3" {
    # All values are supplied via -backend-config=envs/<env>/backend.hcl
    # so this block is intentionally empty.
  }
}

# ── Provider ──────────────────────────────────────────────────────────────────
# All AWS API calls are redirected to LocalStack running locally.
# To deploy to real AWS, remove the `endpoints` block and set real credentials
# via AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY environment variables.
provider "aws" {
  region                      = var.aws_region
  access_key                  = "test"
  secret_key                  = "test"
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true

  endpoints {
    ec2            = var.localstack_endpoint
    rds            = var.localstack_endpoint
    elasticache    = var.localstack_endpoint
    kafka          = var.localstack_endpoint
    iam            = var.localstack_endpoint
    sts            = var.localstack_endpoint
    secretsmanager = var.localstack_endpoint
  }
}

# ── VPC ───────────────────────────────────────────────────────────────────────
module "vpc" {
  source = "./modules/vpc"

  project     = var.project
  environment = var.environment
  vpc_cidr    = var.vpc_cidr
}

# ── RDS (PostgreSQL) ──────────────────────────────────────────────────────────
module "rds" {
  source = "./modules/rds"

  project             = var.project
  environment         = var.environment
  vpc_id              = module.vpc.vpc_id
  subnet_ids          = module.vpc.private_subnet_ids
  allowed_cidr_blocks = [var.vpc_cidr]

  db_name           = var.db_name
  db_username       = var.db_username
  db_password       = var.db_password
  instance_class    = var.rds_instance_class
  allocated_storage = var.rds_allocated_storage
  engine_version    = "16.2"
}

# ── ElastiCache (Redis) ───────────────────────────────────────────────────────
module "elasticache" {
  source = "./modules/elasticache"

  project             = var.project
  environment         = var.environment
  vpc_id              = module.vpc.vpc_id
  subnet_ids          = module.vpc.private_subnet_ids
  allowed_cidr_blocks = [var.vpc_cidr]

  auth_token   = var.redis_auth_token
  node_type    = var.elasticache_node_type
  num_replicas = var.elasticache_num_replicas
}

# ── MSK (Managed Streaming for Kafka) ─────────────────────────────────────────
module "msk" {
  source = "./modules/msk"

  project             = var.project
  environment         = var.environment
  vpc_id              = module.vpc.vpc_id
  subnet_ids          = module.vpc.private_subnet_ids
  allowed_cidr_blocks = [var.vpc_cidr]

  kafka_version        = "3.6.0"
  broker_instance_type = var.msk_broker_instance_type
  num_brokers          = var.msk_num_brokers
  topics               = var.kafka_topics

  # Points the Kafka topic provisioner at the local docker-compose Kafka broker.
  # In real AWS this would be the MSK bootstrap_brokers output.
  compose_working_dir = "${path.root}/../.."
}
