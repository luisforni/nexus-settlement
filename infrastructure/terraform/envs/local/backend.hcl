# LocalStack backend — uses local filesystem state via the S3 LocalStack endpoint.
# This lets the same S3 backend block work locally without real AWS credentials.
#
# Usage:
#   terraform init -backend-config=envs/local/backend.hcl

bucket         = "nexus-tfstate-local"
key            = "nexus-settlement/local/terraform.tfstate"
region         = "us-east-1"
encrypt        = false
dynamodb_table = "nexus-tfstate-lock-local"

# Point the AWS provider and backend at LocalStack
endpoint                    = "http://localhost:4566"
access_key                  = "test"
secret_key                  = "test"
skip_credentials_validation = true
skip_metadata_api_check     = true
skip_requesting_account_id  = true
force_path_style            = true
