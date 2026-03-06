# Architecture — Nexus Settlement

> **Last updated:** 2026-03-05 | **Status:** Living document

---

## Table of Contents

1. [Goals & Non-Goals](#1-goals--non-goals)
2. [System Context (C4 Level 1)](#2-system-context)
3. [Container Diagram (C4 Level 2)](#3-container-diagram)
4. [Service Responsibilities](#4-service-responsibilities)
5. [Data Architecture](#5-data-architecture)
6. [Event Architecture (Kafka)](#6-event-architecture)
7. [API Gateway Design](#7-api-gateway-design)
8. [AI Fraud Detection Pipeline](#8-ai-fraud-detection-pipeline)
9. [Security Architecture](#9-security-architecture)
10. [Scalability & Performance](#10-scalability--performance)
11. [Observability Stack](#11-observability-stack)
12. [Deployment Architecture](#12-deployment-architecture)
13. [Disaster Recovery & HA](#13-disaster-recovery--ha)
14. [ADRs (Architecture Decision Records)](#14-adrs)

---

## 1. Goals & Non-Goals

### Goals
- Process financial settlement transactions with P99 latency < 150 ms at the API layer.
- Detect fraud in real-time (< 50 ms inference) using ML models without blocking settlement flow.
- Achieve 99.9 % availability with no single point of failure.
- Full OWASP Top 10 compliance; PCI-DSS readiness.
- Horizontally scalable to ≥ 5 000 TPS.

### Non-Goals
- User-facing frontend (this is a backend platform; frontends integrate via API Gateway).
- Crypto/blockchain settlement (out of scope v1).
- Card network integration (planned v2).

---

## 2. System Context

```
┌─────────────────────────────────────────────────────────────────┐
│                       External Actors                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ FinTech Apps │  │ Back-office  │  │ Compliance / Auditors│  │
│  │  (REST/HTTPS)│  │  Dashboards  │  │   (read-only API)    │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘  │
└─────────┼─────────────────┼──────────────────────┼─────────────┘
          │ HTTPS / TLS 1.3 │                      │
┌─────────▼─────────────────▼──────────────────────▼─────────────┐
│                    NEXUS SETTLEMENT PLATFORM                     │
│                  (this system — see container diagram)          │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Container Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│ Nexus Settlement Platform                                            │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  API Gateway  (Node.js 20 / TypeScript 5 / Express)         │    │
│  │  • JWT RS256 validation           • Request validation      │    │
│  │  • Redis-backed rate-limiting     • CORS / Helmet / CSP     │    │
│  │  • Structured audit logging       • Circuit breaker         │    │
│  └────────┬─────────────────────────────────┬──────────────────┘    │
│           │ HTTP/2 (internal)               │ HTTP/2 (internal)     │
│  ┌────────▼──────────────┐      ┌───────────▼──────────────────┐    │
│  │  Settlement Service   │      │   Fraud Detection Service    │    │
│  │  Python 3.12/FastAPI  │      │   Python 3.12/FastAPI + ML   │    │
│  │  SQLAlchemy async     │      │   XGBoost + IsolationForest  │    │
│  │  Alembic migrations   │      │   Feature engineering pipeline│   │
│  └────────┬──────────────┘      └───────────┬──────────────────┘    │
│           │                                 │                        │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │              Apache Kafka 3.6  (event bus)                  │    │
│  │  Topics: nexus.settlements · nexus.fraud.alerts             │    │
│  │          nexus.notifications · nexus.audit                  │    │
│  └───────────────────────┬─────────────────────────────────────┘    │
│                          │                                           │
│  ┌────────────────────────▼────────────────────────────────────┐    │
│  │  Notification Service  (Node.js 20 / TypeScript)            │    │
│  │  AWS SES (email) · Twilio (SMS) · Webhook dispatcher        │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  ┌──────────────┐  ┌────────────┐  ┌───────────────────────────┐   │
│  │  PostgreSQL  │  │   Redis    │  │  Prometheus + Grafana     │   │
│  │  16 (primary │  │  7 (cache, │  │  + Loki  (observability)  │   │
│  │  + replica)  │  │  sessions, │  │                           │   │
│  │              │  │  rate-lim) │  │                           │   │
│  └──────────────┘  └────────────┘  └───────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 4. Service Responsibilities

### 4.1 API Gateway
| Concern | Implementation |
|---|---|
| Authentication | JWT RS256; validates `Authorization: Bearer` header; rejects expired/invalid tokens |
| Authorisation | Scopes embedded in JWT claims; RBAC checked per route |
| Rate limiting | Sliding-window algorithm; state stored in Redis; 429 response with `Retry-After` header |
| Input validation | Zod schemas on every incoming request body and query params |
| Routing | Reverse-proxy to downstream services; circuit breaker (opossum) |
| Audit logging | Every request logged to Loki with `correlation-id`, user, IP, latency |

### 4.2 Settlement Service
Owns the **settlement state machine**:
```
PENDING → PROCESSING → COMPLETED
                    ↘ FAILED
                    ↘ REVERSED
```
- Idempotent upsert via `idempotency_key` (UUID v4, required on all mutating requests).
- Optimistic locking with `version` column to prevent concurrent modification.
- Publishes `settlement.created`, `settlement.completed`, `settlement.failed` events to Kafka.

### 4.3 Fraud Detection Service
- **Synchronous path**: called by API Gateway before settlement is accepted. Must respond in < 50 ms.
- **Asynchronous path**: consumes `nexus.settlements` topic and re-scores completed settlements for retrospective analysis.
- Exposes `/api/v1/fraud/score` (real-time) and `/api/v1/fraud/explain` (SHAP feature explanations).
- Model retraining triggered by a separate training pipeline (not in-process).

### 4.4 Notification Service
- Pure Kafka consumer; stateless.
- Consumes `nexus.notifications` topic.
- Providers: AWS SES (email), Twilio (SMS), Webhook (HTTP POST to customer-configured URLs).
- Retry with exponential back-off; dead-letter topic: `nexus.notifications.dlq`.

---

## 5. Data Architecture

### 5.1 Database Design Principles
- **One database per service** — no cross-service foreign keys.
- All PII columns encrypted at rest using PostgreSQL `pgcrypto` + application-level AES-256-GCM.
- Soft deletes only (`deleted_at TIMESTAMPTZ`).
- All timestamps in UTC.

### 5.2 Settlement Service Schema (key tables)
```sql
-- settlements
id                UUID PRIMARY KEY DEFAULT gen_random_uuid()
idempotency_key   UUID UNIQUE NOT NULL          -- OWASP A01: prevents duplicate processing
status            settlement_status NOT NULL    -- enum: PENDING|PROCESSING|COMPLETED|FAILED|REVERSED
amount            NUMERIC(20, 4) NOT NULL
currency          CHAR(3) NOT NULL              -- ISO 4217
payer_id          UUID NOT NULL                 -- references identity service (no FK)
payee_id          UUID NOT NULL
risk_score        NUMERIC(4, 3)                 -- 0.000–1.000, set by fraud-detection
version           INTEGER NOT NULL DEFAULT 1    -- optimistic locking
created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
deleted_at        TIMESTAMPTZ                   -- soft delete
```

### 5.3 Caching Strategy (Redis)
| Use Case | TTL | Key Pattern |
|---|---|---|
| JWT public key | 1 h | `jwt:public_key` |
| Rate limit counter | 1 min sliding window | `rl:{ip}:{route}` |
| Settlement read cache | 30 s | `settlement:{id}` |
| Fraud model metadata | 5 min | `fraud:model:meta` |

---

## 6. Event Architecture

### Topics & Schemas

| Topic | Producer | Consumers | Schema |
|---|---|---|---|
| `nexus.settlements` | settlement-service | fraud-detection | [contracts/settlements.json](../shared/contracts/settlements.json) |
| `nexus.fraud.alerts` | fraud-detection | settlement-service, notification-service | — |
| `nexus.notifications` | settlement-service, fraud-detection | notification-service | — |
| `nexus.audit` | all services | immutable audit sink | — |

### Delivery Guarantees
- Producers use `acks=all` + `enable.idempotence=true`.
- Consumers use manual offset commit after successful processing.
- Exactly-once semantics via Kafka Transactions for settlement-service.

---

## 7. API Gateway Design

### Middleware Pipeline (ordered)
```
Request →
  1. Helmet (security headers)       [OWASP A05]
  2. CORS                            [OWASP A05]
  3. Request ID injection            (correlation-id header)
  4. Structured logger               (Pino)
  5. Rate limiter                    [OWASP A04]
  6. JWT auth                        [OWASP A02]
  7. Input validation (Zod)          [OWASP A03]
  8. Circuit breaker (opossum)
  9. Reverse proxy → upstream
→ Response
  10. Response scrubbing (remove internal headers)
  11. Audit log flush
```

---

## 8. AI Fraud Detection Pipeline

### Feature Engineering
```
Raw transaction event
        │
        ▼
┌───────────────────────────────────┐
│  Feature Engineering (Python)     │
│  • Amount z-score vs. user history│
│  • Velocity: txns last 1m/5m/1h   │
│  • Time-of-day & day-of-week      │
│  • Geographic anomaly (IP→country)│
│  • Payee first-time flag          │
│  • Amount round-number flag       │
└───────────────┬───────────────────┘
                │ feature vector (numpy)
        ┌───────▼────────────────────┐
        │  Ensemble Model            │
        │  XGBoost (primary)         │
        │  + IsolationForest (anomaly│
        │    detection fallback)     │
        └───────┬────────────────────┘
                │ risk_score ∈ [0,1]
        ┌───────▼────────────────────┐
        │  Decision Engine           │
        │  < 0.40 → APPROVE          │
        │  0.40–0.75 → REVIEW        │
        │  > 0.75 → FLAG / BLOCK     │
        └────────────────────────────┘
```

### Model Governance
- Models versioned as artifacts (Joblib) stored in S3 / object storage.
- Model metadata (version, AUC-ROC, training date) exposed via `/api/v1/fraud/model-info`.
- Champion/challenger A/B routing via feature flag (percentage-based split).
- SHAP values available on demand for explainability / regulatory audit.

---

## 9. Security Architecture

Full controls matrix: [SECURITY.md](SECURITY.md)

### Defence in Depth Layers
```
Layer 0  WAF / DDoS protection (CloudFront / Cloudflare)
Layer 1  API Gateway — Auth, Rate-limit, Input sanitisation
Layer 2  Service mesh mTLS (Istio — production Kubernetes)
Layer 3  PostgreSQL row-level security + column encryption
Layer 4  Immutable audit log (Kafka topic, retention 7 years)
Layer 5  Secrets management (HashiCorp Vault — no hardcoded secrets)
```

---

## 10. Scalability & Performance

| Component | Scaling Strategy |
|---|---|
| API Gateway | Horizontal (HPA min 2, max 20 pods); stateless |
| Settlement Service | Horizontal (HPA); DB connection pooling via PgBouncer |
| Fraud Detection | Horizontal; model loaded once per process into RAM |
| Notification | Horizontal; Kafka partition-level parallelism |
| PostgreSQL | Primary + async read replica; PgBouncer session pooling |
| Redis | Redis Cluster (3 masters, 3 replicas) |
| Kafka | 3-broker cluster; topic replication factor 3 |

### Performance Targets

| Metric | Target | Measurement |
|---|---|---|
| API Gateway P99 | < 150 ms | Prometheus histogram |
| Settlement commit | < 300 ms | DB query duration |
| Fraud score (sync) | < 50 ms | Fraud service latency |
| Kafka consumer lag | < 500 ms | kafka_consumer_lag_sum |
| System throughput | ≥ 5 000 TPS | Load test (k6) |

---

## 11. Observability Stack

```
Services → Prometheus metrics (/metrics endpoint)
        → Pino / Python logging → Loki (log aggregation)
        → Distributed tracing → Tempo (OpenTelemetry)

Grafana dashboards:
  • Service RED metrics (Rate, Errors, Duration)
  • Kafka consumer lag
  • PostgreSQL connection pool saturation
  • Fraud score distribution / alert rate
  • Business KPIs (settlement volume, failure rate)

Alerting (PagerDuty / Slack):
  • P99 latency > 500 ms for 2 min → CRITICAL
  • Error rate > 1 % for 5 min → WARNING
  • Kafka lag > 10 000 for 5 min → WARNING
  • Fraud alert rate spike > 3σ → CRITICAL
```

---

## 12. Deployment Architecture

```
GitHub PR
  → CI (workflow ci.yml) — lint, test, Docker build
Merge to main
  → CD — Docker image push to ECR (tagged with SHA)
  → ArgoCD detects new image → rolling update (0 downtime)
  → Smoke tests → promote to production
  → Rollback: ArgoCD one-click previous revision

Environments:
  development   Local Docker Compose
  staging       Kubernetes (EKS) — mirrors production
  production    Kubernetes (EKS) — multi-AZ, HA
```

---

## 13. Disaster Recovery & HA

| Failure Scenario | Mitigation | RTO | RPO |
|---|---|---|---|
| Single pod crash | Kubernetes restart policy | < 30 s | 0 |
| AZ failure | Multi-AZ deployment; PDB min 1 replica | < 60 s | 0 |
| DB primary failure | Automated RDS failover to replica | < 120 s | < 5 s |
| Kafka broker failure | 3-broker cluster; RF=3 | 0 (transparent) | 0 |
| Full region failure | DR region (warm standby via cross-region replication) | < 30 min | < 5 min |

---

## 14. ADRs

| # | Title | Status | Date |
|---|---|---|---|
| ADR-001 | Use Kafka as event bus (vs. RabbitMQ) | Accepted | 2025-11-01 |
| ADR-002 | RS256 JWT over HS256 | Accepted | 2025-11-05 |
| ADR-003 | Python FastAPI for ML services (vs. Node.js) | Accepted | 2025-11-10 |
| ADR-004 | PostgreSQL over MongoDB for settlement data | Accepted | 2025-11-10 |
| ADR-005 | XGBoost + IsolationForest ensemble for fraud | Accepted | 2025-12-01 |
| ADR-006 | Pydantic v2 strict mode for input validation | Accepted | 2026-01-15 |