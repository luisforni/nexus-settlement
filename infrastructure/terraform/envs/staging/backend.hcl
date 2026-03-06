# Staging backend — real AWS S3 + DynamoDB state locking.
#
# Prerequisites:
#   1. The S3 bucket and DynamoDB table must be created ONCE (bootstrap):
#      aws s3api create-bucket --bucket nexus-tfstate-staging --region us-east-1
#      aws s3api put-bucket-versioning --bucket nexus-tfstate-staging \
#        --versioning-configuration Status=Enabled
#      aws s3api put-bucket-encryption --bucket nexus-tfstate-staging \
#        --server-side-encryption-configuration '{
#          "Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
#      aws dynamodb create-table --table-name nexus-tfstate-lock-staging \
#        --attribute-definitions AttributeName=LockID,AttributeType=S \
#        --key-schema AttributeName=LockID,KeyType=HASH \
#        --billing-mode PAY_PER_REQUEST --region us-east-1
#
#   2. Then initialise:
#      terraform init -backend-config=envs/staging/backend.hcl -reconfigure

bucket         = "nexus-tfstate-staging"
key            = "nexus-settlement/staging/terraform.tfstate"
region         = "us-east-1"
encrypt        = true
dynamodb_table = "nexus-tfstate-lock-staging"

# IAM role assumed by CI/CD runners (replace ARN with your account's role)
# role_arn = "arn:aws:iam::123456789012:role/nexus-terraform-staging"
