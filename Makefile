.PHONY: up down build logs test lint health seed \
        test-gateway test-settlement test-fraud test-notification \
        fmt check-security migrate train-model train-deploy deploy-model dev-setup quickstart \
        tf-init tf-plan tf-apply tf-destroy tf-output \
        helm-lint helm-template helm-install helm-upgrade helm-uninstall export-openapi test-integration \
        contract-tests mutate mutate-py pre-commit-install pre-commit-run

TF_DIR := infrastructure/terraform
TF     := terraform -chdir=$(TF_DIR)

COMPOSE := docker compose
PYTHON  := python3.12

up: ## Start all services in detached mode
	$(COMPOSE) up --build -d

down: ## Stop and remove containers, networks
	$(COMPOSE) down --remove-orphans

build: ## Build all Docker images without cache
	$(COMPOSE) build --no-cache

logs: ## Tail logs from all services
	$(COMPOSE) logs -f

restart: ## Restart all services
	$(COMPOSE) restart

health: ## Verify all service health endpoints
	@echo "→ API Gateway"
	@curl -sf http://localhost:4000/healthz | jq .
	@echo "→ Settlement Service"
	@curl -sf http://localhost:18001/api/v1/health | jq .
	@echo "→ Fraud Detection"
	@curl -sf http://localhost:18002/api/v1/fraud/health | jq .
	@echo "→ Notification Service"
	@curl -sf http://localhost:8003/health | jq .

migrate: ## Run Alembic migrations for settlement-service
	$(COMPOSE) exec settlement-service alembic upgrade head

migrate-fraud: ## Run Alembic migrations for fraud-detection
	$(COMPOSE) exec fraud-detection alembic upgrade head

migrate-check: ## Print SQL Alembic would run (dry-run, no DB needed)
	cd services/settlement-service && alembic upgrade --sql head

seed: ## Seed demo data into settlement-service (bypasses gateway auth)
	$(COMPOSE) cp scripts/seed_db.py settlement-service:/tmp/seed_db.py
	$(COMPOSE) exec settlement-service python3.12 /tmp/seed_db.py --url http://localhost:8001

train-model: ## Train fraud detection model inside the running container
	@echo "→ Training fraud detection model (runs inside fraud-detection container)..."
	@mkdir -p services/fraud-detection/artifacts
	$(COMPOSE) exec fraud-detection python3.12 scripts/train_model.py \
		--samples 15000 \
		--fraud-rate 0.08 \
		--output /tmp/fraud_model.joblib
	$(COMPOSE) cp fraud-detection:/tmp/fraud_model.joblib services/fraud-detection/artifacts/fraud_model.joblib
	@echo "✓ Artifact saved → services/fraud-detection/artifacts/fraud_model.joblib"
	@echo "  Run 'make deploy-model' to activate it in the running container."

train-deploy: train-model deploy-model ## Train model and immediately deploy it

deploy-model: ## Copy trained model artifact into the running fraud-detection container
	@ARTIFACT=services/fraud-detection/artifacts/fraud_model.joblib; \
	if [ ! -f "$$ARTIFACT" ]; then \
		echo "ERROR: $$ARTIFACT not found. Run 'make train-model' first." >&2; \
		exit 1; \
	fi
	$(COMPOSE) cp $$ARTIFACT fraud-detection:/app/artifacts/fraud_model.joblib
	$(COMPOSE) restart fraud-detection
	@echo "✓ Model deployed and fraud-detection restarted."

dev-setup: ## Copy .env.example → .env and install local tooling
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "✓ Created .env from .env.example — update secrets before running."; \
	else \
		echo "  .env already exists, skipping."; \
	fi
	@echo "→ Installing Python tooling (settlement-service)"
	@cd services/settlement-service && pip install -q -r requirements.txt
	@echo "→ Installing Python tooling (fraud-detection)"
	@cd services/fraud-detection && pip install -q -r requirements.txt
	@echo "→ Installing Node.js tooling (api-gateway)"
	@cd services/api-gateway && npm ci --silent
	@echo "→ Installing Node.js tooling (notification-service)"
	@cd services/notification-service && npm ci --silent
	@echo "✓ dev-setup complete. Run 'make quickstart' to launch."

quickstart: ## Full first-run: build → up → migrate → seed → health
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  Nexus Settlement — quickstart"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	$(COMPOSE) build
	$(COMPOSE) up -d
	@echo "→ Waiting for services to be healthy…"
	@sleep 15
	@$(MAKE) migrate
	@$(MAKE) seed
	@if [ -f services/fraud-detection/artifacts/fraud_model.joblib ]; then \
		$(MAKE) deploy-model; \
	else \
		echo "  ⚠ No model artifact found — fraud-detection running in rule-based mode."; \
		echo "    Run 'make train-model && make deploy-model' to enable ML scoring."; \
	fi
	@$(MAKE) health
	@echo ""
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  All services running. Endpoints:"
	@echo "    API Gateway  →  http://localhost:4000"
	@echo "    Settlement   →  http://localhost:18001/docs"
	@echo "    Fraud        →  http://localhost:18002/docs"
	@echo "    Kafka UI     →  http://localhost:19080"
	@echo "    Grafana      →  http://localhost:3001  (admin/admin)"
	@echo "    Prometheus   →  http://localhost:9091"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

test: test-gateway test-settlement test-fraud test-notification ## Run all test suites

test-gateway: ## Run API Gateway tests
	$(COMPOSE) exec api-gateway npm test -- --coverage

test-settlement: ## Run Settlement Service tests
	$(COMPOSE) exec settlement-service pytest tests/ -v --cov=app --cov-report=term-missing

test-fraud: ## Run Fraud Detection tests
	$(COMPOSE) exec fraud-detection pytest tests/ -v --cov=app --cov-report=term-missing

test-notification: ## Run Notification Service tests
	$(COMPOSE) exec notification-service npm test -- --coverage

lint: ## Run all linters (ESLint, Ruff, mypy)
	@echo "→ ESLint (api-gateway)"
	$(COMPOSE) exec api-gateway npm run lint
	@echo "→ ESLint (notification-service)"
	$(COMPOSE) exec notification-service npm run lint
	@echo "→ Ruff (settlement-service)"
	$(COMPOSE) exec settlement-service ruff check app/
	@echo "→ mypy (settlement-service)"
	$(COMPOSE) exec settlement-service mypy app/
	@echo "→ Ruff (fraud-detection)"
	$(COMPOSE) exec fraud-detection ruff check app/
	@echo "→ mypy (fraud-detection)"
	$(COMPOSE) exec fraud-detection mypy app/

fmt: ## Auto-format Python with Black and TS with Prettier
	$(COMPOSE) exec settlement-service black app/ tests/
	$(COMPOSE) exec fraud-detection black app/ tests/
	$(COMPOSE) exec api-gateway npm run format
	$(COMPOSE) exec notification-service npm run format

check-security: ## Run Bandit static analysis on Python services
	$(COMPOSE) exec settlement-service bandit -r app/ -ll
	$(COMPOSE) exec fraud-detection bandit -r app/ -ll

contract-tests: ## Run Kafka contract tests (all services, no Docker needed)
	@echo "→ Settlement Service contract tests"
	cd services/settlement-service && pytest tests/test_kafka_contracts.py -v
	@echo "→ Fraud Detection contract tests"
	cd services/fraud-detection && pytest tests/test_kafka_fraud_contracts.py -v
	@echo "→ Notification Service contract tests (TypeScript)"
	cd services/notification-service && npm test -- --testPathPattern=kafka.contracts --no-coverage

mutate: ## Run Stryker mutation tests on TypeScript services
	@echo "→ Notification Service mutation testing"
	cd services/notification-service && npm run mutate
	@echo "→ API Gateway mutation testing"
	cd services/api-gateway && npm run mutate

mutate-py: ## Run mutmut mutation tests on Python services
	@echo "→ Settlement Service mutation testing"
	cd services/settlement-service && mutmut run
	@echo "→ Fraud Detection mutation testing"
	cd services/fraud-detection && mutmut run

pre-commit-install: ## Install pre-commit hooks (run once after cloning)
	pre-commit install
	pre-commit install --hook-type commit-msg
	@echo "✓ pre-commit hooks installed"

pre-commit-run: ## Run all pre-commit hooks against all files
	pre-commit run --all-files

help: ## Print this help
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ── Terraform / LocalStack ────────────────────────────────────────────────────
tf-init: ## Init Terraform providers (requires LocalStack running: make up)
	@echo "→ Initialising Terraform against LocalStack…"
	$(TF) init

tf-plan: ## Show Terraform plan against LocalStack (no changes applied)
	$(TF) plan -var-file="terraform.tfvars.local"

tf-apply: ## Apply Terraform config to LocalStack (creates VPC, RDS, ElastiCache, MSK)
	@echo "→ Applying Terraform against LocalStack…"
	$(TF) apply -var-file="terraform.tfvars.local" -auto-approve
	@echo "→ Outputs:"
	$(TF) output

tf-destroy: ## Destroy all Terraform-managed resources in LocalStack
	$(TF) destroy -var-file="terraform.tfvars.local" -auto-approve

tf-output: ## Show current Terraform output values
	$(TF) output

# ── Helm ─────────────────────────────────────────────────────────────────────
HELM_CHART := infrastructure/helm/nexus-settlement
HELM_RELEASE := nexus-settlement
HELM_NAMESPACE := nexus-settlement

helm-lint: ## Lint the Helm chart
	helm lint $(HELM_CHART)

helm-template: ## Render all Helm templates (dry-run)
	helm template $(HELM_RELEASE) $(HELM_CHART) --namespace $(HELM_NAMESPACE)

helm-install: ## Install the Helm chart into the current kube context
	helm install $(HELM_RELEASE) $(HELM_CHART) \
	  --namespace $(HELM_NAMESPACE) \
	  --create-namespace \
	  --wait

helm-upgrade: ## Upgrade (or install) the Helm release
	helm upgrade --install $(HELM_RELEASE) $(HELM_CHART) \
	  --namespace $(HELM_NAMESPACE) \
	  --create-namespace \
	  --wait

helm-uninstall: ## Uninstall the Helm release
	helm uninstall $(HELM_RELEASE) --namespace $(HELM_NAMESPACE)

# ── OpenAPI spec export ────────────────────────────────────────────────────
export-openapi: ## Export OpenAPI specs for all services to shared/contracts/
	POSTGRES_HOST=localhost POSTGRES_DB=x POSTGRES_USER=x POSTGRES_PASSWORD=x \
	REDIS_URL=redis://localhost KAFKA_BOOTSTRAP_SERVERS=localhost:9092 \
	JWT_PUBLIC_KEY_BASE64=dGVzdA== \
	$(PYTHON) scripts/export_openapi.py

# ── Integration tests ──────────────────────────────────────────────────────
test-integration: ## Run integration tests (requires: make up)
	pip install -q -r tests/integration/requirements.txt
	pytest tests/integration -v -m integration

.DEFAULT_GOAL := help
