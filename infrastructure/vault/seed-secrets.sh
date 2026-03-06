#!/usr/bin/env bash
# infrastructure/vault/seed-secrets.sh
#
# Seeds Vault (dev mode) with all application secrets.
# Run once after `docker-compose up vault`:
#
#   docker-compose exec vault sh /vault/config/seed-secrets.sh
#   # or from the host:
#   bash infrastructure/vault/seed-secrets.sh
#
# The script is idempotent — re-running it is safe.

set -euo pipefail

VAULT_ADDR="${VAULT_ADDR:-http://localhost:8200}"
VAULT_TOKEN="${VAULT_DEV_ROOT_TOKEN:-nexus-dev-root-token}"

export VAULT_ADDR VAULT_TOKEN

echo "━━━ Vault seed: ${VAULT_ADDR} ━━━"

# ── Enable KV v2 secrets engine at nexus/ ─────────────────────────────────
vault secrets enable -path=nexus kv-v2 2>/dev/null || \
  echo "  kv-v2 at nexus/ already enabled"

# ── PostgreSQL credentials ─────────────────────────────────────────────────
vault kv put nexus/postgres \
  host="${POSTGRES_HOST:-postgres}" \
  port="${POSTGRES_PORT:-5432}" \
  db="${POSTGRES_DB:-nexus_settlement}" \
  user="${POSTGRES_USER:-nexus_user}" \
  password="${POSTGRES_PASSWORD:-CHANGE_ME_strong_password_here}"

# ── Redis ──────────────────────────────────────────────────────────────────
vault kv put nexus/redis \
  url="${REDIS_URL:-redis://:CHANGE_ME_strong_redis_password@redis:6379/0}" \
  password="${REDIS_PASSWORD:-CHANGE_ME_strong_redis_password}"

# ── JWT signing keys ───────────────────────────────────────────────────────
vault kv put nexus/jwt \
  private_key_base64="${JWT_PRIVATE_KEY_BASE64:-CHANGE_ME_base64_encoded_rsa_private_key}" \
  public_key_base64="${JWT_PUBLIC_KEY_BASE64:-CHANGE_ME_base64_encoded_rsa_public_key}" \
  algorithm="${JWT_ALGORITHM:-RS256}"

# ── Kafka ──────────────────────────────────────────────────────────────────
vault kv put nexus/kafka \
  bootstrap_servers="${KAFKA_BOOTSTRAP_SERVERS:-kafka:29092}"

# ── External notification channels ────────────────────────────────────────
vault kv put nexus/aws \
  access_key_id="${AWS_ACCESS_KEY_ID:-CHANGE_ME}" \
  secret_access_key="${AWS_SECRET_ACCESS_KEY:-CHANGE_ME}" \
  region="${AWS_REGION:-us-east-1}" \
  ses_from_email="${SES_FROM_EMAIL:-noreply@example.com}"

vault kv put nexus/twilio \
  account_sid="${TWILIO_ACCOUNT_SID:-CHANGE_ME}" \
  auth_token="${TWILIO_AUTH_TOKEN:-CHANGE_ME}" \
  from_number="${TWILIO_FROM_NUMBER:-CHANGE_ME}"

echo ""
echo "✓ Vault secrets seeded successfully."
echo "  UI: ${VAULT_ADDR}/ui  (token: ${VAULT_TOKEN})"
