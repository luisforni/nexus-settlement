#!/usr/bin/env bash
# Bootstrap the Terraform remote state bucket and DynamoDB lock table for a
# given environment. Run ONCE per AWS account before the first `terraform init`.
#
# Usage:
#   ./scripts/bootstrap-backend.sh staging us-east-1
#   ./scripts/bootstrap-backend.sh prod    us-east-1
#
# The script is idempotent — safe to re-run if resources already exist.

set -euo pipefail

ENV="${1:?Usage: $0 <environment> <region>}"
REGION="${2:?Usage: $0 <environment> <region>}"
BUCKET="nexus-tfstate-${ENV}"
TABLE="nexus-tfstate-lock-${ENV}"
KMS_ALIAS="alias/nexus-tfstate-${ENV}"

echo "==> Bootstrapping Terraform backend for: env=${ENV} bucket=${BUCKET} region=${REGION}"

# ── S3 Bucket ─────────────────────────────────────────────────────────────────
if aws s3api head-bucket --bucket "${BUCKET}" 2>/dev/null; then
  echo "    S3 bucket ${BUCKET} already exists — skipping creation"
else
  if [ "${REGION}" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "${BUCKET}" --region "${REGION}"
  else
    aws s3api create-bucket --bucket "${BUCKET}" --region "${REGION}" \
      --create-bucket-configuration LocationConstraint="${REGION}"
  fi
  echo "    Created S3 bucket: ${BUCKET}"
fi

# Enable versioning so state history is preserved
aws s3api put-bucket-versioning \
  --bucket "${BUCKET}" \
  --versioning-configuration Status=Enabled

# Block all public access (state files must never be public)
aws s3api put-public-access-block \
  --bucket "${BUCKET}" \
  --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

# Enable server-side encryption with a customer-managed KMS key
if ! aws kms describe-key --key-id "${KMS_ALIAS}" 2>/dev/null; then
  KEY_ID=$(aws kms create-key \
    --description "Nexus Terraform state encryption key (${ENV})" \
    --query 'KeyMetadata.KeyId' --output text)
  aws kms create-alias --alias-name "${KMS_ALIAS}" --target-key-id "${KEY_ID}"
  echo "    Created KMS key: ${KEY_ID} alias: ${KMS_ALIAS}"
fi

aws s3api put-bucket-encryption \
  --bucket "${BUCKET}" \
  --server-side-encryption-configuration "{
    \"Rules\": [{
      \"ApplyServerSideEncryptionByDefault\": {
        \"SSEAlgorithm\": \"aws:kms\",
        \"KMSMasterKeyID\": \"${KMS_ALIAS}\"
      },
      \"BucketKeyEnabled\": true
    }]
  }"

echo "    S3 bucket configured: versioned + encrypted + public-access-blocked"

# ── DynamoDB Lock Table ───────────────────────────────────────────────────────
if aws dynamodb describe-table --table-name "${TABLE}" --region "${REGION}" 2>/dev/null; then
  echo "    DynamoDB table ${TABLE} already exists — skipping creation"
else
  aws dynamodb create-table \
    --table-name "${TABLE}" \
    --attribute-definitions AttributeName=LockID,AttributeType=S \
    --key-schema AttributeName=LockID,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
    --region "${REGION}"
  echo "    Created DynamoDB table: ${TABLE}"
fi

echo "==> Backend bootstrap complete."
echo ""
echo "Next step:"
echo "  terraform init -backend-config=envs/${ENV}/backend.hcl -reconfigure"
