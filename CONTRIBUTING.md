# Contributing to Nexus Settlement

Thank you for taking the time to contribute! This document explains the process for reporting bugs, proposing features, and submitting pull requests.

---

## Table of Contents

1. [Code of Conduct](#code-of-conduct)
2. [Getting Started](#getting-started)
3. [Development Workflow](#development-workflow)
4. [Commit Messages](#commit-messages)
5. [Pull Request Process](#pull-request-process)
6. [Testing Requirements](#testing-requirements)
7. [Security Vulnerabilities](#security-vulnerabilities)
8. [Style Guides](#style-guides)

---

## Code of Conduct

All contributors are expected to be respectful and professional. Harassment or discrimination of any kind will not be tolerated.

---

## Getting Started

### Prerequisites

| Tool | Version |
|------|---------|
| Docker + Docker Compose | ≥ 24.x |
| Node.js | ≥ 20.x |
| Python | ≥ 3.12 |
| Terraform | ≥ 1.7 |
| Helm | ≥ 3.14 |
| pre-commit | ≥ 3.x |

### Local setup

```bash
# 1. Clone the repo
git clone https://github.com/your-org/nexus-settlement.git
cd nexus-settlement

# 2. Install pre-commit hooks (mandatory — CI enforces the same checks)
pip install pre-commit
pre-commit install
pre-commit install --hook-type commit-msg

# 3. Verify/update the secrets baseline (detect-secrets)
# .secrets.baseline is committed to the repo — do NOT delete it.
# If you add new files, regenerate it:
pip install detect-secrets
python3 -m detect_secrets scan \
  --exclude-files '(\.git|node_modules|\.terraform|__pycache__|\.joblib|package-lock\.json|\.keys)' \
  > .secrets.baseline
# Then audit any new findings: python3 -m detect_secrets audit .secrets.baseline

# 4. Start the full local stack
make up

# 5. Run all tests
make test
```

---

## Development Workflow

1. **Branch naming**: `feat/<short-description>`, `fix/<issue-number>-<description>`, `chore/<description>`
2. **Keep branches short-lived** — aim for PRs that can be reviewed in a single sitting.
3. **One concern per PR** — avoid mixing feature work with refactoring.
4. **Local validation before pushing**:
   ```bash
   make lint test
   pre-commit run --all-files
   ```

### Service-specific commands

```bash
# API Gateway (TypeScript)
cd services/api-gateway
npm test
npm run lint
npm run typecheck

# Settlement Service (Python)
cd services/settlement-service
pytest --cov=app
ruff check app/ tests/

# Fraud Detection (Python)
cd services/fraud-detection
pytest --cov=app

# Notification Service (TypeScript)
cd services/notification-service
npm test
npm run lint
```

---

## Commit Messages

Follow the [Conventional Commits](https://www.conventionalcommits.org/) specification:

```
<type>(<scope>): <short summary>

[optional body]

[optional footer: BREAKING CHANGE, Closes #N]
```

**Types**: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `ci`, `perf`, `security`

**Examples**:
```
feat(settlement-service): add DLQ processor with configurable retry count

Implements a dead-letter queue consumer that re-injects messages up to
KAFKA_DLQ_MAX_RETRIES times before permanently failing them.

Closes #42
```

```
security(api-gateway): tighten rate limit to 60 req/min in prod values

Reduces the default from 100 to 60 requests per minute in values-prod.yaml
to align with the threat model in SECURITY.md.
```

---

## Pull Request Process

1. **Open a draft PR early** to get feedback before the implementation is complete.
2. **Fill in the PR template** — describe what changed and why, not how.
3. **Link to the issue** using `Closes #N` or `Relates to #N`.
4. **CI must pass** — all checks in `.github/workflows/ci.yml` and `security-scan.yml`.
5. **Coverage must not drop** — the per-service 80% threshold is enforced by CI.
6. **At least one approval** from a maintainer is required before merging.
7. **Squash-merge** into `main` — keep the history linear.

### PR checklist

- [ ] Tests added or updated for every changed behaviour
- [ ] `CHANGELOG.md` updated under `[Unreleased]`
- [ ] Documentation updated if public interfaces changed
- [ ] No new `TODO` / `FIXME` added without a linked issue
- [ ] `pre-commit run --all-files` passes locally
- [ ] No secrets committed (detect-secrets baseline updated if needed)

---

## Testing Requirements

| Requirement | Tool | Threshold |
|---|---|---|
| Unit test coverage | pytest-cov / jest | ≥ 80% lines |
| Mutation score (new code) | mutmut / Stryker | ≥ 60% (low threshold) → raise to 75% |
| Contract validation | jsonschema / ajv | All new events must pass schema |
| Integration tests | pytest / jest (httpx) | Must pass in CI against Docker Compose stack |

### Running contract tests

```bash
# Python services
cd services/settlement-service
pytest tests/test_kafka_contracts.py -v

cd services/fraud-detection
pytest tests/test_kafka_fraud_contracts.py -v

# Notification service (TypeScript)
cd services/notification-service
npm test -- tests/kafka.contracts.test.ts
```

### Running mutation tests

```bash
# Python (settlement-service)
cd services/settlement-service
pip install mutmut
mutmut run

# TypeScript (notification-service)
cd services/notification-service
npm run mutate
```

---

## Security Vulnerabilities

**Do not open a public GitHub issue for security vulnerabilities.**

Please follow the responsible disclosure process described in [SECURITY.md](SECURITY.md). We aim to respond within 48 hours and issue a patch within 7 days for critical findings.

---

## Style Guides

### Python

- Linter: **ruff** (configured in each service's `pyproject.toml`)
- Formatter: **ruff format** (enforced by pre-commit)
- Type checker: **mypy** in strict mode
- Max line length: 100 characters

### TypeScript

- Linter: **ESLint** with `@typescript-eslint` rules
- Formatter: **Prettier**
- Strict mode enabled in all `tsconfig.json` files

### Infrastructure

- Terraform: `terraform fmt` enforced by pre-commit
- Kubernetes YAML: validated by `kubectl --dry-run=client`
- Helm: `helm lint` run in CI

### Documentation

- Markdown files should be checked with `markdownlint`
- Architecture decisions go in `docs/ARCHITECTURE.md`
- Operational procedures go in `docs/RUNBOOK.md`
