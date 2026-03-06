# Nexus Settlement — Deployment Runbook

**Document owner**: Platform Engineering
**Last updated**: 2026-03-10
**Scope**: Kubernetes (EKS) + Helm + ArgoCD deployments

---

## Table of Contents

1. [Pre-deployment checklist](#1-pre-deployment-checklist)
2. [Deploying to staging](#2-deploying-to-staging)
3. [Deploying to production](#3-deploying-to-production)
4. [Canary and blue-green rollout](#4-canary-and-blue-green-rollout)
5. [Rollback procedure](#5-rollback-procedure)
6. [JWT secret rotation](#6-jwt-secret-rotation)
7. [Database migrations](#7-database-migrations)
8. [Kafka topic management](#8-kafka-topic-management)
9. [Vault secret rotation](#9-vault-secret-rotation)
10. [Observability during deployments](#10-observability-during-deployments)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. Pre-deployment checklist

Before triggering any deployment, verify:

- [ ] All CI checks pass on the release branch (GitHub Actions: `ci.yml` + `security-scan.yml`)
- [ ] Trivy and Bandit scans show no critical vulnerabilities in new images
- [ ] `CHANGELOG.md` updated with the release notes
- [ ] Alembic migrations reviewed — no destructive DDL without a multi-phase rollout plan
- [ ] Kafka schema changes are backwards-compatible (new optional fields only)
- [ ] Vault secrets for the target environment are seeded (`seed-secrets.sh`)
- [ ] Terraform state for the environment is clean (`terraform plan` shows no unexpected changes)
- [ ] On-call engineer is available for the deployment window

---

## 2. Deploying to staging

Staging deploys happen automatically via ArgoCD when the `develop` branch is updated.
For manual deploys:

```bash
# Sync the staging application immediately (skips the automated sync interval)
argocd app sync nexus-settlement-staging --prune

# Watch the rollout
argocd app wait nexus-settlement-staging --health --timeout 300

# Verify all pods are running
kubectl -n nexus-staging get pods -w
```

### Smoke test staging

```bash
export GATEWAY_URL=https://api.staging.nexus-settlement.example.com
export INTEGRATION_TEST_TOKEN="$(./scripts/generate_test_token.sh)"

cd tests/integration
pytest test_settlement_flow.py test_fraud_flow.py -v --tb=short
```

---

## 3. Deploying to production

Production deployments follow a **progressive rollout** strategy (see §4).

### 3.1 Tag the release

```bash
git tag -a v1.2.0 -m "Release v1.2.0"
git push origin v1.2.0
```

CI automatically builds and pushes images tagged with the semver tag.

### 3.2 Update image tags

```bash
# In values-prod.yaml — set ALL services to the new semver tag
sed -i 's/tag: ".*"/tag: "1.2.0"/' \
  infrastructure/helm/nexus-settlement/values-prod.yaml

git commit -am "chore: release v1.2.0"
git push origin main
```

### 3.3 Sync via ArgoCD

ArgoCD auto-syncs `main → nexus-settlement`. Monitor the sync:

```bash
argocd app sync nexus-settlement
argocd app wait nexus-settlement --health --sync --timeout 600
```

### 3.4 Verify production health

```bash
# All pods Running
kubectl -n nexus-settlement get pods

# P99 latency — should remain < 500ms throughout rollout
kubectl -n nexus-settlement top pods

# Check Grafana dashboards
open https://grafana.internal.example.com/d/nexus-settlement-service
```

---

## 4. Canary and blue-green rollout

### 4.1 Canary deployment (recommended for settlement-service)

Istio weight-based traffic splitting allows routing a percentage of live traffic
to the new version before full rollout.

```yaml
# infrastructure/k8s/istio/canary-vs.yaml (apply manually during rollout)
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: settlement-service-canary
  namespace: nexus-settlement
spec:
  hosts: ["settlement-service"]
  http:
    - route:
        - destination:
            host: settlement-service
            subset: stable
          weight: 90
        - destination:
            host: settlement-service
            subset: canary
          weight: 10   # 10% → 25% → 50% → 100% over 30-minute windows
```

```bash
# Deploy the canary (new image tag on a separate Deployment)
kubectl -n nexus-settlement set image deployment/settlement-service-canary \
  settlement-service=nexus/settlement-service:1.2.0

# Monitor canary error rate for 15 minutes
watch -n 5 'kubectl -n nexus-settlement get pods -l version=canary'

# Promote to 100% — delete canary VirtualService, update main Deployment
kubectl -n nexus-settlement delete virtualservice settlement-service-canary
kubectl -n nexus-settlement set image deployment/settlement-service \
  settlement-service=nexus/settlement-service:1.2.0
```

**Abort canary**: set `weight: 0` on the canary subset and delete the canary Deployment.

### 4.2 Blue-green deployment (for breaking changes)

```bash
# 1. Deploy new "green" Deployment alongside existing "blue"
kubectl -n nexus-settlement apply -f k8s/settlement-service-green.yaml

# 2. Wait for green to become healthy
kubectl -n nexus-settlement rollout status deployment/settlement-service-green

# 3. Smoke test green (internal Service, not exposed externally yet)
kubectl -n nexus-settlement port-forward svc/settlement-service-green 18001:8001 &
curl -fs http://localhost:18001/health

# 4. Switch traffic by patching the Service selector
kubectl -n nexus-settlement patch service settlement-service \
  -p '{"spec":{"selector":{"version":"green"}}}'

# 5. Verify, then delete blue
kubectl -n nexus-settlement delete deployment settlement-service-blue
```

---

## 5. Rollback procedure

### Immediate rollback (< 5 minutes)

```bash
# Helm rollback to the previous release
helm rollback nexus-settlement --namespace nexus-settlement

# Or via ArgoCD — set targetRevision to the previous Git SHA
argocd app set nexus-settlement --revision <PREVIOUS_SHA>
argocd app sync nexus-settlement
```

### Rollback with Kubernetes

```bash
# View rollout history
kubectl -n nexus-settlement rollout history deployment/settlement-service

# Roll back to the previous revision
kubectl -n nexus-settlement rollout undo deployment/settlement-service

# Roll back to a specific revision
kubectl -n nexus-settlement rollout undo deployment/settlement-service --to-revision=3
```

### When to rollback

Trigger a rollback immediately if any of the following are observed within 10 minutes of a deploy:

- 5xx error rate > 2% sustained for > 2 minutes
- P99 latency > 1s sustained for > 3 minutes
- Settlement DLQ depth > 20 messages
- Fraud detection block rate surge > 20% (model regression)
- Any pod CrashLoopBackOff that does not self-resolve

---

## 6. JWT secret rotation

JWT secret rotation requires a **two-phase rollout** because rotating the secret
immediately invalidates all active tokens.

### Phase 1 — Add the new key alongside the old one

```bash
# Generate a new RS256 key pair
openssl genrsa -out /tmp/jwt_new.pem 4096
openssl rsa -in /tmp/jwt_new.pem -pubout -out /tmp/jwt_new_pub.pem

# Load both keys into Vault (the API gateway loads all keys for verification)
vault kv put nexus/api-gateway \
  jwt_private_key=@/tmp/jwt_new.pem \
  jwt_public_key=@/tmp/jwt_new_pub.pem \
  jwt_public_key_old=@/tmp/jwt_old_pub.pem   # Keep old key for token validation

# Rolling restart so the gateway picks up both keys
kubectl -n nexus-settlement rollout restart deployment/api-gateway
```

### Phase 2 — Remove the old key (after token TTL has elapsed)

Wait for `JWT_EXPIRY_MINUTES` (default: 60 minutes) before Phase 2.

```bash
# Remove the old public key from Vault
vault kv patch nexus/api-gateway jwt_public_key_old=""

# Rolling restart
kubectl -n nexus-settlement rollout restart deployment/api-gateway
```

---

## 7. Database migrations

Alembic migrations run as a **Kubernetes Job** before the settlement-service Deployment
is updated. The Helm chart handles this as a `pre-upgrade` hook.

```bash
# Run migrations manually (e.g. if the hook failed)
kubectl -n nexus-settlement run --rm -it alembic-migrate \
  --image=nexus/settlement-service:1.2.0 \
  --restart=Never \
  -- alembic upgrade head

# Verify migration status
kubectl -n nexus-settlement run --rm -it alembic-check \
  --image=nexus/settlement-service:1.2.0 \
  --restart=Never \
  -- alembic current
```

### Destructive migration checklist

For migrations that DROP columns or tables:

- [ ] Deploy the new code **without** removing the column (backward-compatible)
- [ ] Let the new code run for at least one full deployment cycle
- [ ] Confirm no queries are using the old column (check slow-query logs)
- [ ] Run the DROP in a separate migration

---

## 8. Kafka topic management

```bash
# List topics
kubectl -n nexus-settlement exec -it kafka-0 -- \
  kafka-topics.sh --bootstrap-server kafka:9092 --list

# Inspect consumer lag
kubectl -n nexus-settlement exec -it kafka-0 -- \
  kafka-consumer-groups.sh --bootstrap-server kafka:9092 \
  --describe --group nexus-settlement-processor

# Create a missing topic
kubectl -n nexus-settlement exec -it kafka-0 -- \
  kafka-topics.sh --bootstrap-server kafka:9092 --create \
  --topic nexus.settlements.dlq --partitions 3 --replication-factor 3

# Reset consumer group offset (DANGEROUS — only for DLQ draining)
kubectl -n nexus-settlement exec -it kafka-0 -- \
  kafka-consumer-groups.sh --bootstrap-server kafka:9092 \
  --group nexus-dlq-processor --reset-offsets \
  --topic nexus.settlements.dlq --to-latest --execute
```

---

## 9. Vault secret rotation

Automated rotation runs as a CronJob every Sunday at 03:00 UTC.

```bash
# Trigger manual rotation (dry run first)
kubectl -n nexus-settlement create job --from=cronjob/vault-secret-rotation \
  vault-rotation-manual-$(date +%s)

# Watch rotation job logs
kubectl -n nexus-settlement logs -f job/vault-rotation-manual-...

# Check if services have picked up new secrets (rolling restart triggered by the job)
kubectl -n nexus-settlement rollout status deployment/settlement-service
kubectl -n nexus-settlement rollout status deployment/notification-service
```

See [docs/SECURITY.md](SECURITY.md) for the full secrets policy.

---

## 10. Observability during deployments

Monitor these Grafana dashboards throughout any production deployment:

| Dashboard | Key panels | Alert threshold |
|-----------|-----------|----------------|
| Settlement Service | P99 latency, error rate, DLQ depth | P99 > 500ms OR error > 1% |
| Fraud Detection | Scoring latency P99, block rate | P99 > 200ms OR block rate > 15% |
| Infrastructure | Kafka consumer lag, DB connections | Lag > 1000 OR pool > 90% |

### Useful kubectl commands during rollout

```bash
# Watch pod replacement in real-time
kubectl -n nexus-settlement get pods -w

# Check that the Readiness probe passes before traffic is routed
kubectl -n nexus-settlement describe pod <pod-name> | grep -A5 Readiness

# Tail application logs across all settlement-service pods
kubectl -n nexus-settlement logs -l app=settlement-service -f --max-log-requests=10
```

---

## 11. Troubleshooting

### Pod stuck in CrashLoopBackOff

```bash
kubectl -n nexus-settlement describe pod <pod>
kubectl -n nexus-settlement logs <pod> --previous
```

Common causes:
- Missing environment variable → check Vault secret seeding
- Database connection failure → verify `POSTGRES_HOST` and network policy
- Port conflict → check Service definition

### Settlement DLQ depth growing

```bash
# Inspect DLQ messages
kubectl -n nexus-settlement exec -it kafka-0 -- \
  kafka-console-consumer.sh --bootstrap-server kafka:9092 \
  --topic nexus.settlements.dlq --from-beginning --max-messages 10

# Check DLQ processor logs
kubectl -n nexus-settlement logs -l app=settlement-service -f \
  | grep -i dlq
```

### Fraud model not loading

```bash
# Verify the model artifact exists on the PVC
kubectl -n nexus-settlement exec -it <fraud-detection-pod> -- \
  ls -lh /app/artifacts/

# Re-run the retrain CronJob manually
kubectl -n nexus-settlement create job --from=cronjob/fraud-model-retrain retrain-manual
```

### ArgoCD sync failed

```bash
argocd app get nexus-settlement
argocd app history nexus-settlement
argocd app rollback nexus-settlement <revision>
```
