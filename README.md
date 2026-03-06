# Nexus Settlement

> **FinTech · Distributed Settlement System with AI Fraud Detection**
>
> High-performance, event-driven, microservices monorepo — OWASP Top 10 compliant · PEP 8 · 99.9 % SLA target

[![CI](https://github.com/luisforni/nexus-settlement/actions/workflows/ci.yml/badge.svg)](https://github.com/luisforni/nexus-settlement/actions/workflows/ci.yml)
[![Security Scan](https://github.com/luisforni/nexus-settlement/actions/workflows/security-scan.yml/badge.svg)](https://github.com/luisforni/nexus-settlement/actions/workflows/security-scan.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Repository Structure](#repository-structure)
- [Technology Stack](#technology-stack)
- [Technology Decisions](#technology-decisions)
- [Quick Start](#quick-start)
- [Services](#services)
- [Security](#security)
- [Performance](#performance)
- [Contributing](#contributing)

---

## Architecture Overview

Nexus Settlement is built on an **event-driven microservices** architecture. All inter-service communication is asynchronous via Apache Kafka. Synchronous calls go through the API Gateway, which enforces authentication, rate-limiting, and request validation before proxying upstream.

```
┌──────────────────────────────────────────────────────────┐
│                        Clients                           │
└──────────────────────┬───────────────────────────────────┘
                       │ HTTPS / TLS 1.3
┌──────────────────────▼───────────────────────────────────┐
│              API Gateway  (Node.js / TypeScript)          │
│   JWT Auth · Rate Limit · CORS · Helmet · WAF Rules      │
└───────┬──────────────────────────────┬────────────────────┘
        │ REST / HTTP/2                │ REST / HTTP/2
┌───────▼──────────┐        ┌──────────▼─────────────────┐
│ Settlement Svc   │        │  Fraud Detection Svc        │
│ Python / FastAPI │        │  Python / FastAPI + ML      │
│ SQLAlchemy / PG  │        │  scikit-learn / XGBoost     │
└───────┬──────────┘        └──────────┬──────────────────┘
        │ Kafka events                 │ Kafka events
┌───────▼──────────────────────────────▼──────────────────┐
│                 Apache Kafka (event bus)                  │
└───────────────────────────┬──────────────────────────────┘
                            │
              ┌─────────────▼─────────────┐
              │  Notification Service      │
              │  Node.js / TypeScript      │
              │  Email · SMS · Webhook     │
              └────────────────────────────┘

Shared infrastructure: PostgreSQL · Redis · Prometheus · Grafana · Loki
```

---

## Repository Structure

```
nexus-settlement/
├── .github/
│   └── workflows/
│       ├── ci.yml                  # Build + lint + test on every PR
│       └── security-scan.yml       # OWASP ZAP + Trivy + Bandit nightly
│
├── services/
│   ├── api-gateway/                # Node.js 20 LTS / TypeScript 5
│   │   ├── src/
│   │   │   ├── app.ts
│   │   │   ├── config/index.ts
│   │   │   ├── middleware/
│   │   │   │   ├── auth.ts         # JWT RS256 validation
│   │   │   │   ├── rateLimiter.ts  # Redis-backed sliding window
│   │   │   │   ├── security.ts     # Helmet, CORS, CSP, HPP
│   │   │   │   └── logger.ts       # Pino structured logging
│   │   │   └── routes/
│   │   │       ├── settlements.ts
│   │   │       ├── fraud.ts
│   │   │       └── health.ts
│   │   ├── Dockerfile
│   │   ├── package.json
│   │   └── tsconfig.json
│   │
│   ├── settlement-service/         # Python 3.12 / FastAPI
│   │   ├── app/
│   │   │   ├── api/v1/endpoints/
│   │   │   │   ├── settlements.py  # CRUD + state machine
│   │   │   │   └── health.py
│   │   │   ├── core/               # config, security, logging
│   │   │   ├── db/                 # SQLAlchemy async engine
│   │   │   ├── models/             # ORM models
│   │   │   ├── schemas/            # Pydantic v2 schemas
│   │   │   ├── services/           # Business logic layer
│   │   │   └── messaging/          # Kafka producer
│   │   ├── tests/
│   │   ├── Dockerfile
│   │   ├── pyproject.toml
│   │   └── requirements.txt
│   │
│   ├── fraud-detection/            # Python 3.12 / FastAPI + ML
│   │   ├── app/
│   │   │   ├── api/v1/endpoints/fraud.py
│   │   │   ├── core/
│   │   │   ├── models/             # ML model classes (XGBoost, IsolationForest)
│   │   │   │   ├── fraud_detector.py
│   │   │   │   └── feature_engineering.py
│   │   │   └── services/fraud_service.py
│   │   ├── tests/
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   │
│   └── notification-service/       # Node.js 20 LTS / TypeScript 5
│       ├── src/
│       │   ├── app.ts
│       │   ├── handlers/notification.handler.ts
│       │   └── providers/          # Email (SES), SMS (Twilio), Webhook
│       ├── Dockerfile
│       └── package.json
│
├── shared/
│   └── contracts/                  # JSON Schema contracts (API + Kafka events)
│
├── infrastructure/
│   ├── k8s/                        # Kubernetes manifests (Deployment, HPA, PDB)
│   └── terraform/                  # Cloud infra (VPC, RDS, ElastiCache, MSK)
│
├── scripts/
│   ├── setup.sh                    # Dev environment bootstrap
│   └── seed_db.py                  # Demo data seeder
│
├── docs/
│   ├── ARCHITECTURE.md
│   ├── SECURITY.md                 # OWASP Top 10 controls matrix
│   └── API.md                      # OpenAPI endpoint reference
│
├── .env.example
├── .gitignore
├── docker-compose.yml
├── Makefile
└── README.md
```

---

## Technology Stack

| Layer | Technology | Version |
|---|---|---|
| API Gateway | Node.js + Express + TypeScript | Node 20 LTS / TS 5 |
| Settlement Service | Python + FastAPI + SQLAlchemy | Python 3.12 |
| Fraud Detection | Python + FastAPI + XGBoost | Python 3.12 |
| Notification | Node.js + TypeScript | Node 20 LTS |
| Database (primary) | PostgreSQL | 16 |
| Cache / Rate-limit | Redis | 7 |
| Message Bus | Apache Kafka + Zookeeper | Kafka 3.6 |
| Observability | Prometheus + Grafana + Loki | latest stable |
| Secret management | HashiCorp Vault | 1.15 |
| Container runtime | Docker + Docker Compose | Compose v2 |
| Orchestration | Kubernetes (EKS / GKE) | 1.29 |
| IaC | Terraform | 1.7 |
| CI/CD | GitHub Actions | — |

---

## Technology Decisions

### API Gateway — Node.js + Express + TypeScript

Financial platforms receive bursts of concurrent HTTP traffic. Node.js's non-blocking I/O model handles thousands of simultaneous connections on a single thread without the overhead of thread-per-request frameworks. TypeScript was chosen over plain JavaScript to enforce strict types across the gateway's route handlers, middleware, and proxy logic — catching contract mismatches between services at compile time rather than at runtime in production.

Express was preferred over more opinionated frameworks (Fastify, NestJS) because the gateway's sole responsibility is authentication, rate-limiting, and proxying: a thin, composable middleware stack fits that requirement precisely.

### Settlement & Fraud Detection — Python + FastAPI

Python is the dominant language in the financial data-science ecosystem. Using it for the settlement service keeps the stack consistent with the fraud detection service, which relies on scikit-learn and XGBoost — libraries with no comparable equivalents in Node.js or Go.

FastAPI was selected over Flask or Django REST Framework for three reasons: native async support via Python's `asyncio` (critical for non-blocking database and Kafka I/O), automatic OpenAPI documentation generation from Pydantic schemas (essential for inter-team contracts), and built-in request validation with clear error responses. Django's ORM and admin panel are unnecessary weight for pure API services.

### PostgreSQL — Primary Database

PostgreSQL 16 offers ACID guarantees, row-level locking, and native support for JSONB metadata fields — all necessary for financial settlement records where consistency and auditability are non-negotiable. The `uuid-ossp` and `pgcrypto` extensions provide cryptographically secure identifiers and PGP encryption at the storage layer.

MySQL was considered but rejected because PostgreSQL's `SERIALIZABLE` isolation level and advisory locks offer stronger guarantees for concurrent settlement state transitions. SQLAlchemy's async engine (`asyncpg` driver) adds connection pooling, parameterised queries (preventing SQL injection), and schema migration via Alembic.

### Redis — Cache and Rate Limiting

Redis was chosen as the rate-limit store because it provides sub-millisecond atomic operations (`INCRBY`, `EXPIRE`) across distributed gateway replicas. A local in-process counter would break when the gateway scales horizontally. Redis's LRU eviction policy keeps memory bounded, and its persistence options (AOF) allow recovery after restarts without losing sliding-window state.

### Apache Kafka — Event Bus

Settlement events must be durable, ordered per-partition, and replayable for audit. Kafka's log-based architecture satisfies all three: messages are persisted to disk and can be replayed by any downstream consumer. This is fundamentally different from a traditional message queue (RabbitMQ, SQS) where messages are deleted after acknowledgement — the notification service, future analytics pipelines, and audit log consumers can all independently read from the same Kafka topics without coordination.

Kafka's decoupling also provides natural backpressure: if the notification service is slow, it lags behind without affecting the settlement service's throughput.

### XGBoost + IsolationForest — Fraud Detection

XGBoost was selected as the primary classifier because gradient-boosted trees consistently outperform deep learning on structured tabular financial data (amount, currency, velocity, payer/payee relationships) with limited training samples. Deep neural networks require significantly more data and are harder to explain to compliance teams.

IsolationForest acts as an unsupervised anomaly detector for patterns not seen during training. The ensemble score (70% XGBoost + 30% IsolationForest) reduces false negatives on novel fraud patterns without relying solely on supervised labels. SHAP values are computed on demand to provide feature-level explanations — a requirement in many jurisdictions (EU AI Act, SR 11-7).

### Prometheus + Grafana — Observability

Prometheus's pull-based scrape model fits containerised environments well: each service exposes a `/metrics` endpoint and Prometheus discovers targets via Docker service labels or Kubernetes pod annotations — no need to configure each service to push metrics to a central endpoint.

Grafana was chosen over commercial alternatives (Datadog, New Relic) to keep the stack self-hosted and cost-predictable. Dashboards are provisioned as code under `infrastructure/monitoring/grafana/provisioning`, making them fully reproducible across environments.

### RS256 JWT — Authentication

Asymmetric RS256 (RSA + SHA-256) was chosen over symmetric HS256 because it allows downstream services (settlement, fraud) to verify token signatures using only the public key — without sharing a secret. If a downstream service is compromised, the attacker cannot forge tokens because they only hold the public key. The gateway is the sole service that holds the private key, maintaining a single issuance boundary.

---

## Quick Start

### Prerequisites

- Docker ≥ 24 and Docker Compose v2
- `make` (optional but recommended)
- Node.js 20 LTS (for local gateway dev)
- Python 3.12 + pip (for local service dev)

### Bootstrap

```bash
# 1. Clone
git clone https://github.com/luisforni/nexus-settlement.git
cd nexus-settlement

# 2. Copy environment config
cp .env.example .env
# Edit .env — at minimum set strong secrets for JWT_PRIVATE_KEY, POSTGRES_PASSWORD, etc.

# 3. Start full stack (first run downloads images and builds services)
make up
# or: docker compose up --build -d

# 4. Verify all services are healthy
make health
# or: docker compose ps

# 5. Seed demo data
make seed

# 6. Open API docs (FastAPI auto-generated)
#    Settlement service: http://localhost:8001/docs
#    Fraud detection:    http://localhost:8002/docs
```

### Useful Make targets

```bash
make up          # Start all containers detached
make down        # Stop and remove containers
make logs        # Tail all service logs
make test        # Run all service test suites
make lint        # Lint (ESLint + Black + Ruff + mypy)
make health      # Hit /healthz on each service
make seed        # Load demo settlement data
make build       # Build all Docker images
```

---

## Services

| Service | Host Port | Notes |
|---|---|---|
| API Gateway | 4000 | Single public entry point |
| Settlement Service | 18001 | Internal — exposed for local dev only |
| Fraud Detection | 18002 | Internal — exposed for local dev only |
| Notification Service | 8003 | Internal — exposed for local dev only |
| Prometheus | 9091 | Metrics UI — `/graph` |
| Grafana | 3001 | Dashboards — login: admin/admin123 |
| Kafka UI | 19080 | Topic browser |

---

## Security

Security posture is documented in detail in [docs/SECURITY.md](docs/SECURITY.md).

Key controls:

- **A01 Broken Access Control** — RBAC enforced at gateway + service level; deny-by-default.
- **A02 Cryptographic Failures** — TLS 1.3; AES-256-GCM at rest; RS256 JWTs; Argon2id password hashes.
- **A03 Injection** — SQLAlchemy ORM (parameterised); Pydantic strict validation; no raw SQL.
- **A05 Security Misconfiguration** — Helmet + CSP; no default credentials (`.env.example` only has placeholders); read-only containers.
- **A06 Vulnerable Components** — Trivy + Dependabot + Bandit in CI; nightly SBOM generation.
- **A09 Logging & Monitoring** — Structured JSON logs → Loki; alerts in Grafana; audit log immutable stream to Kafka.

---

## Performance

| Metric | Target |
|---|---|
| P99 API latency | < 150 ms |
| Throughput | ≥ 5 000 TPS (horizontal) |
| Availability | 99.9 % (≤ 8.7 h/year downtime) |
| Fraud decision time | < 50 ms (in-memory inference) |
| Kafka consumer lag | < 500 ms |

---

## Contributing

1. Fork → feature branch (`feat/your-feature`)
2. Follow [PEP 8](https://peps.python.org/pep-0008/) for Python and ESLint config for TypeScript.
3. Write tests (≥ 80 % coverage required by CI).
4. Open a PR — must pass all CI checks + security scan before merge.

4. **Run the tests**:
   ```bash
   npm test
   ```

