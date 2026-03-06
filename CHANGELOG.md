# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
- Vault secrets rotation CronJob (`infrastructure/k8s/vault-rotation-cronjob.yaml`)
- Terraform remote state with S3 + DynamoDB locking for staging and production environments
- Grafana dashboards for fraud-detection and infrastructure
- Prometheus alerting rules and Alertmanager routing configuration
- GitOps manifests for ArgoCD (project, application, staging application)
- Pre-commit hook configuration (detect-secrets, ruff, prettier, Terraform fmt, hadolint)
- Mutation testing setup (Stryker for TypeScript services, mutmut for Python services)
- Kafka contract tests validating event schemas for settlement and fraud events
- Notification service test coverage: channel unit tests + Kafka consumer tests

---

## [1.0.0] — 2026-03-10

### Added

#### Services
- **api-gateway** (Node.js 20 / Express / TypeScript)
  - JWT RS256 authentication middleware
  - Redis-backed rate limiting (Ioredis + express-rate-limit)
  - Opossum circuit breaker for upstream calls
  - Prometheus `/metrics` endpoint
  - OpenTelemetry distributed tracing (OTLP/HTTP exporter)

- **settlement-service** (Python 3.12 / FastAPI / SQLAlchemy async)
  - Full settlement lifecycle state machine (PENDING → PROCESSING → COMPLETED / FAILED / CANCELLED / REVERSED)
  - Kafka producer/consumer with idempotency key support
  - Optimistic locking (version column) to prevent race conditions
  - Dead Letter Queue processor with configurable retry count
  - HashiCorp Vault integration for secret injection at startup
  - Alembic database migrations
  - OpenTelemetry tracing (FastAPI + SQLAlchemy + httpx auto-instrumentation)

- **fraud-detection** (Python 3.12 / FastAPI / XGBoost / SHAP)
  - XGBoost + IsolationForest ensemble model
  - SHAP explainability on `/api/v1/fraud/explain`
  - Rule-based overrides (hardcoded thresholds for high-risk patterns)
  - Automated retraining pipeline with AUC gate and atomic artifact swap
  - K8s CronJob for nightly model retraining at 02:00 UTC

- **notification-service** (Node.js 20 / KafkaJS / TypeScript)
  - Multi-channel dispatch: AWS SES email, Twilio SMS, HTTPS webhook
  - SSRF protection on webhook URLs (RFC-1918 + loopback blocklist)
  - DLQ permanently-failed event handler
  - Integrity hash verification on inbound Kafka envelopes

#### Infrastructure
- Docker Compose stack with 16 services (all four microservices + Kafka, PostgreSQL, Redis, OTel Collector, Tempo, Prometheus, Grafana, Vault, LocalStack)
- Kubernetes manifests: Deployments, Services, NetworkPolicies, Pod Disruption Budgets
- Istio mTLS configuration: `PeerAuthentication: STRICT`, `AuthorizationPolicy` (SPIFFE identities), `VirtualService` (timeouts + retries)
- Helm chart (`infrastructure/helm/nexus-settlement/`) with 9 templates covering all services, HPA, PDB, Ingress, Secrets, and the retrain CronJob
- Terraform modules for AWS VPC, RDS PostgreSQL, ElastiCache Redis, MSK Kafka (LocalStack simulation)
- HashiCorp Vault with KV v2, least-privilege policies, idempotent secret seeder
- GitHub Actions CI (`ci.yml`): path-based builds, 80% coverage threshold
- GitHub Actions security scan (`security-scan.yml`): Trivy, Bandit, OWASP ZAP, SBOM generation

#### Testing
- Unit tests for all four services (65+ tests total)
- Integration test suite (`tests/integration/`) with async httpx fixtures
- k6 load tests: 5K RPS settlement, 2K RPS fraud scoring, 30-minute soak test
- Kafka contract tests: JSON Schema validation for settlement and fraud-alert event schemas

#### Observability
- Grafana dashboard for Settlement Service (TPS, P99 latency, error rate, DB pool)
- OpenAPI spec export script and generated specs in `shared/contracts/`

#### Shared Contracts
- `shared/contracts/settlement-event.json` — JSON Schema (Draft-07) for all settlement lifecycle events
- `shared/contracts/fraud-alert-event.json` — JSON Schema for fraud detection decisions

---

## [0.1.0] — 2026-01-15 *(internal prototype)*

### Added
- Initial project scaffold with four service directories
- Basic FastAPI and Express skeletons
- Docker Compose for local development
- Kafka topic configuration

[Unreleased]: https://github.com/your-org/nexus-settlement/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/your-org/nexus-settlement/compare/v0.1.0...v1.0.0
[0.1.0]: https://github.com/your-org/nexus-settlement/releases/tag/v0.1.0
