# Security — Nexus Settlement

> **Standard:** OWASP Top 10 (2021 edition) + additional FinTech controls
> **Last reviewed:** 2026-03-05

---

## OWASP Top 10 Controls Matrix

| # | Risk | Status | Implementation |
|---|---|---|---|
| A01 | Broken Access Control | ✅ Implemented | See §1 |
| A02 | Cryptographic Failures | ✅ Implemented | See §2 |
| A03 | Injection | ✅ Implemented | See §3 |
| A04 | Insecure Design | ✅ Implemented | See §4 |
| A05 | Security Misconfiguration | ✅ Implemented | See §5 |
| A06 | Vulnerable & Outdated Components | ✅ Implemented | See §6 |
| A07 | Identification & Authentication Failures | ✅ Implemented | See §7 |
| A08 | Software & Data Integrity Failures | ✅ Implemented | See §8 |
| A09 | Security Logging & Monitoring Failures | ✅ Implemented | See §9 |
| A10 | Server-Side Request Forgery (SSRF) | ✅ Implemented | See §10 |

---

## §1 — A01: Broken Access Control

**Threat:** Attackers bypass access restrictions to access unauthorised resources.

### Controls
- **RBAC enforced at gateway level**: roles (`admin`, `operator`, `readonly`, `service`) embedded in JWT `scope` claim. Routes are decorated with required roles; any mismatch → 403.
- **Deny-by-default**: all routes require authentication unless explicitly marked public (only `/healthz` and `/api/v1/health`).
- **Object-level authorisation**: settlement records are scoped to `payer_id` / `payee_id`; even authenticated requests cannot access another user's data (IDOR prevention).
- **Service-to-service auth**: internal calls between services use short-lived service JWTs, not user tokens.
- **PostgreSQL row-level security (RLS)**: database enforces tenant isolation at the storage layer as a second enforcement point.

---

## §2 — A02: Cryptographic Failures

**Threat:** Sensitive data exposed due to weak or missing encryption.

### Controls
- **TLS 1.3 only** — TLS 1.0/1.1/1.2 disabled on load balancer and API Gateway.
- **JWT algorithm: RS256** — asymmetric algorithm; private key never leaves the signing service. HS256 is explicitly rejected (`algorithms: ['RS256']` only).
- **Password storage**: Argon2id (memory: 64 MB, iterations: 3, parallelism: 4). bcrypt not used (insufficient for GPU attacks).
- **PII encryption at rest**: sensitive fields (account numbers, names) encrypted with AES-256-GCM before writing to PostgreSQL via `pgcrypto`. Keys managed by HashiCorp Vault.
- **Key rotation**: JWT signing keys rotated every 90 days; database encryption keys rotated annually via Vault's key rotation API.
- **Secrets management**: all secrets injected at runtime from HashiCorp Vault. `.env` files contain only non-sensitive defaults. No hardcoded credentials anywhere (enforced by `detect-secrets` pre-commit hook and Trivy in CI).
- **HSTS**: `Strict-Transport-Security: max-age=31536000; includeSubDomains; preload` injected by Helmet.

---

## §3 — A03: Injection

**Threat:** Attacker-controlled data interpreted as code or commands.

### Controls
- **SQL Injection**: SQLAlchemy ORM with parameterised queries exclusively. Raw SQL is banned by Ruff lint rule. No string interpolation in queries.
- **Input validation**: Pydantic v2 (strict mode) on all Python services; Zod on all TypeScript services. Types, lengths, patterns, and ranges validated before any business logic.
- **NoSQL Injection**: No MongoDB or NoSQL database, eliminating this vector.
- **Command Injection**: no `shell=True` in Python (enforced by Bandit S603/S604 rules); no `exec()`/`eval()` (Bandit B307).
- **SSTI (Server-Side Template Injection)**: no server-rendered templates. All responses are JSON.
- **Mass assignment**: Pydantic schemas use explicit field declarations; `model_config = ConfigDict(extra='forbid')` rejects unknown fields.

---

## §4 — A04: Insecure Design

**Threat:** Missing or ineffective security controls by design.

### Controls
- **Threat modelling**: STRIDE model applied per service during design review.
- **Idempotency**: all mutating endpoints require `Idempotency-Key` header (UUID v4). Duplicate requests return cached response without re-processing, preventing double-charge.
- **Settlement state machine**: transitions validated server-side; invalid transitions → 409 Conflict. Clients cannot force arbitrary state changes.
- **Rate limiting**: sliding-window algorithm in Redis; per-IP and per-user limits; exponential back-off on auth failures.
- **Fraud gate**: settlement creation blocked synchronously if fraud score > threshold. Design prevents accepting funds before fraud check completes.

---

## §5 — A05: Security Misconfiguration

### Controls
- **Helmet middleware** (API Gateway): sets `X-Content-Type-Options`, `X-Frame-Options: DENY`, `X-XSS-Protection`, `Referrer-Policy: no-referrer`, `Permissions-Policy`.
- **Content Security Policy**: `default-src 'none'` for API responses (no HTML served).
- **CORS**: allowlist-only origins; credentials mode requires explicit opt-in.
- **No default credentials**: `.env.example` contains only placeholder values; CI fails if real secrets detected.
- **Read-only containers**: Docker containers run as non-root user (`USER appuser`); filesystem is read-only except for explicit tmpfs mounts.
- **Minimal attack surface**: each service only exposes the port it needs; `backend` Docker network is `internal: true` (not routable from host).
- **Dependency pinning**: all Docker base images pinned to SHA digest in production Dockerfiles.
- **Security headers scanner**: `securityheaders.com` score A+ verified in staging before every production release.

---

## §6 — A06: Vulnerable & Outdated Components

### Controls
- **Trivy**: scans container images and repository on every PR and nightly. Fails CI on HIGH/CRITICAL CVEs.
- **Bandit**: Python SAST runs on every PR (settlement-service, fraud-detection).
- **npm audit**: runs `--audit-level=high` on every PR for Node.js services.
- **OWASP Dependency Check**: nightly scan; CVSS ≥ 7.0 fails the build.
- **Dependabot**: enabled for all `package.json` and `requirements.txt` files; auto-merges patch updates with passing CI.
- **SBOM**: CycloneDX SBOM generated on every main branch build and stored as a release artifact.
- **Renovate**: optional — can replace Dependabot for grouped dependency updates.

---

## §7 — A07: Identification & Authentication Failures

### Controls
- **JWT RS256**: stateless authentication; tokens expire in 15 minutes (access) / 7 days (refresh).
- **Token storage**: clients must store tokens in memory only (not localStorage — documented in API guide).
- **Refresh token rotation**: each use of a refresh token issues a new one and invalidates the old (stored hash in Redis).
- **Brute-force protection**: rate limiter applies exponential back-off after N failed auth attempts per IP; account lockout after M failures.
- **No enumeration**: auth endpoints return identical responses for "user not found" and "wrong password" cases (timing-safe comparison).
- **Session invalidation**: logout endpoint deletes refresh token hash from Redis; all subsequent refresh attempts rejected.

---

## §8 — A08: Software & Data Integrity Failures

### Controls
- **CI/CD pipeline integrity**: all GitHub Actions pinned to commit SHA (not mutable tags).
- **Docker image signing**: images signed with Cosign (Sigstore) before push to ECR; Kubernetes admission controller rejects unsigned images.
- **Kafka message integrity**: settlement events include `sha256` hash of payload; consumers verify before processing.
- **Idempotency keys**: prevent replay attacks on settlement creation.
- **No untrusted deserialisation**: Python services use Pydantic (safe JSON parsing only); `pickle` is banned (Bandit B301-B302).
- **Dependency lock files**: `package-lock.json` and `requirements.txt` (pinned versions) committed and verified in CI (`pip install --require-hashes`).

---

## §9 — A09: Security Logging & Monitoring Failures

### Controls
- **Structured JSON logging**: all services use Pino (Node.js) or Python `structlog`. Logs include `correlation_id`, `user_id`, `ip`, `method`, `path`, `status`, `latency_ms`.
- **Audit log**: every data mutation event published to `nexus.audit` Kafka topic. Topic is append-only, retention = 7 years (regulatory requirement). Separate sink service writes to immutable S3/GCS bucket.
- **Log aggregation**: logs shipped to Loki; queryable via Grafana.
- **Security event alerting**:
  - Auth failures > 10/min from single IP → PagerDuty `critical`
  - Fraud alert rate spike > 3σ → Slack `#security`
  - JWT validation errors spike → Slack `#security`
- **No sensitive data in logs**: Pino `redact` configuration masks `authorization`, `password`, `token`, `card_number`, `account_number` fields.
- **Log integrity**: logs forwarded to immutable destination; CloudTrail / GCP Audit Logs for infrastructure events.

---

## §10 — A10: Server-Side Request Forgery (SSRF)

### Controls
- **No user-controlled URLs**: services do not make HTTP requests to URLs supplied by end users.
- **Allowlist for outbound requests**: Notification Service (webhooks) validates destination URLs against an allowlist stored in the database; private IP ranges (RFC 1918, loopback, link-local) are rejected.
- **DNS rebinding protection**: webhook dispatcher resolves DNS and verifies the resolved IP is not in a reserved range before making the connection.
- **Network egress control**: production Kubernetes applies `NetworkPolicy` to restrict pod egress to known destinations only.

---

## Additional FinTech Controls

### PCI-DSS Alignment
- No cardholder data stored (settlement operates on account IDs, not card numbers).
- All connections to external payment networks use mTLS.
- Network segmentation enforced via Kubernetes `NetworkPolicy`.

### Secrets Rotation Runbook
1. Rotate JWT keys: update Vault secret → restart API Gateway pods → old tokens expire within 15 min.
2. Rotate DB password: update Vault secret → rolling restart of services → PgBouncer picks up new credentials.
3. Rotate Kafka SASL credentials: update Kafka ACLs → update Vault → rolling restart.

### Penetration Testing
- Annual black-box pen test by certified third-party.
- Quarterly internal DAST scan using OWASP ZAP.
- Bug bounty program (responsible disclosure policy in `SECURITY_POLICY.md`).

### Threat Model Summary (STRIDE)

| Threat | Vector | Mitigation |
|---|---|---|
| Spoofing | JWT forgery | RS256; short expiry |
| Tampering | Request body modification | Zod/Pydantic validation; Kafka message hash |
| Repudiation | Deny performing action | Immutable audit log |
| Information Disclosure | Log data leakage | Pino redact; no PII in logs |
| Denial of Service | Request flooding | Rate limiting; HPA; WAF |
| Elevation of Privilege | Scope manipulation | Server-side RBAC; deny-by-default |
- Regularly review and analyze logs to detect suspicious behavior and potential breaches.