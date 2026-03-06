# Production backend — real AWS S3 + DynamoDB state locking.
# State bucket is versioned, server-side encrypted with KMS, and public-access blocked.
#
# Prerequisites:
#   Run infrastructure/terraform/scripts/bootstrap-backend.sh once per account.
#   See that script for the full bucket + table creation commands.
#
# Usage:
#   terraform init -backend-config=envs/prod/backend.hcl -reconfigure

bucket         = "nexus-tfstate-prod"
key            = "nexus-settlement/prod/terraform.tfstate"
region         = "us-east-1"
encrypt        = true
kms_key_id     = "alias/nexus-tfstate-prod"   # Customer-managed KMS key
dynamodb_table = "nexus-tfstate-lock-prod"

# IAM role assumed by CI/CD runners with least-privilege S3 + DynamoDB access
# role_arn = "arn:aws:iam::123456789012:role/nexus-terraform-prod"
