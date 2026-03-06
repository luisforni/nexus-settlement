#!/usr/bin/env bash
# =============================================================================
# scripts/setup.sh — nexus-settlement developer bootstrap
#
# Usage:
#   ./scripts/setup.sh [--skip-deps]
#
# What it does:
#   1. Checks required tooling (Docker, Node 20, Python 3.12, make).
#   2. Copies .env.example -> .env (if not already present).
#   3. Installs Node dependencies for TypeScript services.
#   4. Creates Python virtual environments for Python services.
#   5. Generates a local RSA-2048 key pair for JWT RS256 signing.
# =============================================================================

set -euo pipefail
IFS=$'\n\t'

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKIP_DEPS="${1:-}"

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ── Prereq checks ─────────────────────────────────────────────────────────────
check_command() {
  if ! command -v "$1" &>/dev/null; then
    error "Required command not found: $1"
    error "Please install $2 and re-run this script."
    exit 1
  fi
}

info "Checking prerequisites..."
check_command docker     "Docker (https://docs.docker.com/get-docker/)"
check_command docker     "Docker Compose v2"
check_command node       "Node.js 20 LTS (https://nodejs.org)"
check_command python3    "Python 3.12 (https://python.org)"
check_command make       "GNU Make"
check_command openssl    "OpenSSL"

NODE_MAJOR=$(node --version | sed 's/v//' | cut -d. -f1)
if [[ "$NODE_MAJOR" -lt 20 ]]; then
  error "Node.js 20+ required, found $NODE_MAJOR"
  exit 1
fi

PY_MINOR=$(python3 --version | cut -d. -f2)
if [[ "$PY_MINOR" -lt 12 ]]; then
  warn "Python 3.12+ recommended; found 3.${PY_MINOR}. Continuing..."
fi

info "All prerequisites satisfied."

# ── .env setup ────────────────────────────────────────────────────────────────
ENV_FILE="${REPO_ROOT}/.env"
ENV_EXAMPLE="${REPO_ROOT}/.env.example"

if [[ ! -f "$ENV_FILE" ]]; then
  cp "$ENV_EXAMPLE" "$ENV_FILE"
  info "Created .env from .env.example — review and update values before running services."
else
  warn ".env already exists — skipping copy."
fi

# ── JWT key pair ──────────────────────────────────────────────────────────────
KEYS_DIR="${REPO_ROOT}/.keys"
mkdir -p "$KEYS_DIR"

if [[ ! -f "${KEYS_DIR}/jwt_private.pem" ]]; then
  info "Generating RSA-2048 key pair for JWT RS256..."
  openssl genrsa -out "${KEYS_DIR}/jwt_private.pem" 2048
  openssl rsa -in "${KEYS_DIR}/jwt_private.pem" \
              -pubout -out "${KEYS_DIR}/jwt_public.pem"
  chmod 600 "${KEYS_DIR}/jwt_private.pem"
  info "Keys written to ${KEYS_DIR}/"
  warn "Update JWT_PRIVATE_KEY and JWT_PUBLIC_KEY in .env with the contents of these files."
else
  warn "JWT keys already exist at ${KEYS_DIR}/ — skipping generation."
fi

if [[ "$SKIP_DEPS" == "--skip-deps" ]]; then
  info "Skipping dependency installation (--skip-deps)."
  exit 0
fi

# ── Node.js services ──────────────────────────────────────────────────────────
NODE_SERVICES=("api-gateway" "notification-service")

for svc in "${NODE_SERVICES[@]}"; do
  SVC_DIR="${REPO_ROOT}/services/${svc}"
  if [[ -f "${SVC_DIR}/package.json" ]]; then
    info "Installing Node deps for ${svc}..."
    (cd "$SVC_DIR" && npm ci --ignore-scripts)
    info "  ✓ ${svc}"
  else
    warn "  ${svc}/package.json not found — skipping."
  fi
done

# ── Python services ───────────────────────────────────────────────────────────
PY_SERVICES=("settlement-service" "fraud-detection")

for svc in "${PY_SERVICES[@]}"; do
  SVC_DIR="${REPO_ROOT}/services/${svc}"
  if [[ -f "${SVC_DIR}/requirements.txt" ]]; then
    info "Setting up Python venv for ${svc}..."
    python3 -m venv "${SVC_DIR}/.venv"
    "${SVC_DIR}/.venv/bin/pip" install --quiet --upgrade pip
    "${SVC_DIR}/.venv/bin/pip" install --quiet -r "${SVC_DIR}/requirements.txt"
    info "  ✓ ${svc} (.venv created)"
  else
    warn "  ${svc}/requirements.txt not found — skipping."
  fi
done

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
info "Setup complete. Next steps:"
echo "  1. Edit .env with your secrets and service URLs."
echo "  2. Run 'make up' to start all services."
echo "  3. Run 'make seed' to populate demo data."
echo "  4. Run 'make test' to execute the full test suite."
