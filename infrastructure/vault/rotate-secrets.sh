#!/usr/bin/env bash
# Vault secret rotation script.
# Generates new credentials for each secret path and updates Vault KV v2.
# Run as a CronJob (see infrastructure/k8s/vault-rotation-cronjob.yaml) or
# manually: ./rotate-secrets.sh
#
# Required environment variables:
#   VAULT_ADDR   — e.g. http://vault:8200
#   VAULT_TOKEN  — Vault token with write access to nexus/* paths
#
# Optional:
#   DRY_RUN=true — print what would be rotated without writing to Vault

set -euo pipefail

VAULT_ADDR="${VAULT_ADDR:?VAULT_ADDR must be set}"
VAULT_TOKEN="${VAULT_TOKEN:?VAULT_TOKEN must be set}"
DRY_RUN="${DRY_RUN:-false}"

log() { echo "[$(date -u +%FT%TZ)] $*"; }
vault_write() {
  local path="$1"; shift
  if [ "${DRY_RUN}" = "true" ]; then
    log "DRY RUN — would write to ${path}: $*"
    return
  fi
  curl -sf -X POST \
    -H "X-Vault-Token: ${VAULT_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "$1" \
    "${VAULT_ADDR}/v1/${path}" >/dev/null
  log "Updated secret: ${path}"
}

# ── Helpers ───────────────────────────────────────────────────────────────────

# Generate a cryptographically secure random password of given length
gen_password() {
  local length="${1:-32}"
  LC_ALL=C tr -dc 'A-Za-z0-9!@#%^&*_+=' </dev/urandom | head -c "${length}"
}

# Generate a random hex string (e.g. for API keys, HMAC secrets)
gen_hex() {
  local bytes="${1:-32}"
  head -c "${bytes}" /dev/urandom | xxd -p -c 9999
}

# ── Rotation tasks ────────────────────────────────────────────────────────────

log "Starting secret rotation (DRY_RUN=${DRY_RUN})"

# 1. PostgreSQL password
log "Rotating PostgreSQL password..."
NEW_PG_PASS="$(gen_password 40)"
vault_write "nexus/data/settlement-service" \
  "{\"data\":{\"postgres_password\":\"${NEW_PG_PASS}\"}}"

# 2. Redis password
log "Rotating Redis password..."
NEW_REDIS_PASS="$(gen_password 32)"
vault_write "nexus/data/settlement-service" \
  "{\"data\":{\"redis_password\":\"${NEW_REDIS_PASS}\"}}"

# 3. JWT signing secret (HMAC) — rotated separately; requires coordinated rollout
# NOTE: Rotating the JWT secret invalidates all existing tokens.
# Use a two-phased rollout: add new secret, wait for tokens to expire, remove old.
log "Skipping JWT secret rotation — requires coordinated rollout (see runbook section 5.2)"

# 4. Kafka SASL password
log "Rotating Kafka SASL password..."
NEW_KAFKA_PASS="$(gen_password 32)"
vault_write "nexus/data/settlement-service" \
  "{\"data\":{\"kafka_password\":\"${NEW_KAFKA_PASS}\"}}"

# 5. Notification service Twilio auth token — skipped; managed via Twilio console
log "Skipping Twilio token rotation — managed via Twilio API key lifecycle"

# 6. Notification service AWS SES credentials
log "Rotating AWS SES credentials..."
NEW_AWS_KEY="$(gen_hex 20)"
NEW_AWS_SECRET="$(gen_hex 40)"
vault_write "nexus/data/notification-service" \
  "{\"data\":{\"aws_access_key_id\":\"${NEW_AWS_KEY}\",\"aws_secret_access_key\":\"${NEW_AWS_SECRET}\"}}"

log "Secret rotation complete."

# ── Post-rotation: trigger rolling restarts ─────────────────────────────────
# If running inside the cluster, bounce affected deployments so they pick up
# the new secrets via the Vault agent sidecar / init container.
if [ "${DRY_RUN}" != "true" ] && command -v kubectl &>/dev/null; then
  log "Triggering rolling restarts to pick up new credentials..."
  kubectl -n nexus-settlement rollout restart deployment/settlement-service || true
  kubectl -n nexus-settlement rollout restart deployment/notification-service || true
  log "Rolling restarts initiated. Monitor with: kubectl -n nexus-settlement rollout status deployment"
fi
