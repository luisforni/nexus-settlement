# Deployment Strategy: Canary & Blue-Green

**Document owner**: Platform Engineering
**Scope**: Nexus Settlement — Kubernetes (EKS + Istio) + ArgoCD

---

## Table of Contents

1. [Strategy selection guide](#1-strategy-selection-guide)
2. [Canary deployment](#2-canary-deployment)
3. [Blue-green deployment](#3-blue-green-deployment)
4. [Automated rollback triggers](#4-automated-rollback-triggers)
5. [Database migration compatibility](#5-database-migration-compatibility)
6. [Zero-downtime considerations](#6-zero-downtime-considerations)
7. [Feature flags](#7-feature-flags)

---

## 1. Strategy selection guide

| Change type | Recommended strategy |
|-------------|-------------------|
| API or business logic change | **Canary** (gradual traffic shift, Istio) |
| Breaking API change or schema replacement | **Blue-green** (instant switchover, zero overlap) |
| Infrastructure-only (config, resource limits) | **Rolling update** (default Kubernetes) |
| Database DDL with backward-incompatible schema | **Multi-phase blue-green** with feature flag |
| ML model release (fraud detection) | **Canary with shadow mode** (compare decisions) |

---

## 2. Canary deployment

### 2.1 Prerequisites

- Istio installed in the cluster (`istioctl version`)
- DestinationRule with `stable` and `canary` subsets defined (see below)
- Prometheus metrics scraped from all pods

### 2.2 Define stable and canary subsets

```yaml
# infrastructure/k8s/istio/destination-rules.yaml
apiVersion: networking.istio.io/v1beta1
kind: DestinationRule
metadata:
  name: settlement-service
  namespace: nexus-settlement
spec:
  host: settlement-service
  subsets:
    - name: stable
      labels:
        version: stable
    - name: canary
      labels:
        version: canary
```

```bash
kubectl apply -f infrastructure/k8s/istio/destination-rules.yaml
```

### 2.3 Deploy the canary version

```bash
# Tag canary pods differently from stable pods
kubectl -n nexus-settlement apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: settlement-service-canary
  namespace: nexus-settlement
spec:
  replicas: 1                          # Start with 1 replica (≈10% with 3 stable pods)
  selector:
    matchLabels:
      app: settlement-service
      version: canary
  template:
    metadata:
      labels:
        app: settlement-service
        version: canary
    spec:
      containers:
        - name: settlement-service
          image: nexus/settlement-service:1.2.0   # New version
          # (same env, resources, probes as the stable deployment)
EOF
```

### 2.4 Apply a VirtualService to split traffic

```yaml
# infrastructure/k8s/istio/canary-vs.yaml
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: settlement-service
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
          weight: 10
```

```bash
kubectl apply -f infrastructure/k8s/istio/canary-vs.yaml
```

### 2.5 Progressive traffic shift

Allow at least **15 minutes** at each step and verify the acceptance criteria (§4)
before proceeding.

| Step | Stable | Canary | Wait |
|------|--------|--------|------|
| 1 | 90% | 10% | 15 min |
| 2 | 75% | 25% | 15 min |
| 3 | 50% | 50% | 30 min |
| 4 | 0% | 100% | Promote |

```bash
# Shift to 25% canary
kubectl -n nexus-settlement patch virtualservice settlement-service \
  --type=json \
  -p='[{"op":"replace","path":"/spec/http/0/route/0/weight","value":75},
       {"op":"replace","path":"/spec/http/0/route/1/weight","value":25}]'
```

### 2.6 Promote to 100%

```bash
# 1. Delete the VirtualService (all traffic now goes to the Service selector)
kubectl -n nexus-settlement delete virtualservice settlement-service

# 2. Update the stable Deployment to the new image
kubectl -n nexus-settlement set image deployment/settlement-service \
  settlement-service=nexus/settlement-service:1.2.0

# 3. Wait for rollout
kubectl -n nexus-settlement rollout status deployment/settlement-service

# 4. Delete the canary Deployment
kubectl -n nexus-settlement delete deployment settlement-service-canary
```

### 2.7 Abort canary

```bash
# Set canary weight to 0 and delete the canary Deployment
kubectl -n nexus-settlement patch virtualservice settlement-service \
  --type=json \
  -p='[{"op":"replace","path":"/spec/http/0/route/0/weight","value":100},
       {"op":"replace","path":"/spec/http/0/route/1/weight","value":0}]'

kubectl -n nexus-settlement delete deployment settlement-service-canary
kubectl -n nexus-settlement delete virtualservice settlement-service
```

---

## 3. Blue-green deployment

Blue-green is used when two versions cannot coexist (e.g. breaking API or schema change).

### 3.1 Deploy the green stack

```bash
# Apply the green Deployment with a separate Service
kubectl -n nexus-settlement apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: settlement-service-green
  namespace: nexus-settlement
spec:
  replicas: 3
  selector:
    matchLabels:
      app: settlement-service
      slot: green
  template:
    metadata:
      labels:
        app: settlement-service
        slot: green
    spec:
      containers:
        - name: settlement-service
          image: nexus/settlement-service:1.2.0
---
apiVersion: v1
kind: Service
metadata:
  name: settlement-service-green
  namespace: nexus-settlement
spec:
  selector:
    app: settlement-service
    slot: green
  ports:
    - port: 8001
      targetPort: 8001
EOF
```

### 3.2 Smoke test the green stack

```bash
# Port-forward to the green Service (not exposed externally yet)
kubectl -n nexus-settlement port-forward svc/settlement-service-green 18001:8001 &

curl -fs http://localhost:18001/health | jq .
curl -fs http://localhost:18001/api/v1/settlements?limit=1 \
  -H "Authorization: Bearer $TEST_TOKEN" | jq .

kill %1
```

### 3.3 Atomic traffic switch

```bash
# Patch the production Service to point at the green pods
kubectl -n nexus-settlement patch service settlement-service \
  -p '{"spec":{"selector":{"app":"settlement-service","slot":"green"}}}'
```

The switchover is instantaneous. Any in-flight requests to old (blue) pods
complete normally because Kubernetes waits for connections to drain
(termination grace period: 30 s).

### 3.4 Verify, then clean up

```bash
# Verify production is healthy after the switch
sleep 60
curl -fs https://api.nexus-settlement.example.com/api/v1/settlements?limit=1 \
  -H "Authorization: Bearer $TEST_TOKEN" | jq .

# If healthy, remove the blue Deployment
kubectl -n nexus-settlement delete deployment settlement-service       # old blue
kubectl -n nexus-settlement delete service settlement-service-green   # internal test svc

# Rename green to stable for future round-trips
kubectl -n nexus-settlement patch deployment settlement-service-green \
  --type=json \
  -p='[{"op":"replace","path":"/metadata/name","value":"settlement-service"}]'
```

### 3.5 Revert (switch back to blue)

```bash
# If the green stack is unhealthy, switch traffic back to the blue pods
kubectl -n nexus-settlement patch service settlement-service \
  -p '{"spec":{"selector":{"app":"settlement-service","slot":"blue"}}}'
```

---

## 4. Automated rollback triggers

Prometheus alert rules (defined in `infrastructure/monitoring/alerts/alert-rules.yml`)
automatically fire when the following thresholds are exceeded.

| Alert | Condition | Action |
|-------|-----------|--------|
| `SettlementErrorRateHigh` | 5xx rate > 2% for 2 min | PagerDuty + manual rollback |
| `SettlementP99LatencyHigh` | P99 > 500ms for 5 min | PagerDuty + manual rollback |
| `SettlementDLQDepthHigh` | DLQ depth > 10 messages | Slack + investigate |
| `ApiGatewayErrorRateHigh` | 5xx rate > 5% for 2 min | PagerDuty + manual rollback |
| `FraudBlockRateSurge` | Block rate > 15% for 5 min | Risk team email + investigate |

### Manual rollback

```bash
# Helm
helm rollback nexus-settlement --namespace nexus-settlement

# Kubernetes native
kubectl -n nexus-settlement rollout undo deployment/settlement-service

# Blue-green — switch selector back to blue slot
kubectl -n nexus-settlement patch service settlement-service \
  -p '{"spec":{"selector":{"slot":"blue"}}}'
```

---

## 5. Database migration compatibility

### Expand/contract (recommended)

Never make a breaking schema change in a single deployment. Instead:

**Phase 1 — Expand** (deploy with the new code AND old code both working)
- Add the new column as `NULLABLE` with no default
- New code writes to both old and new columns
- Old code reads from the old column (ignores the new one)

**Phase 2 — Backfill**
```sql
UPDATE settlements SET new_column = derive(old_column) WHERE new_column IS NULL;
```

**Phase 3 — Contract** (after confirming old code is fully retired)
- Add `NOT NULL` constraint
- Drop the old column in a separate migration

### Pod Disruption Budget

Ensure a PDB is applied to prevent all pods being taken down during node drain:

```yaml
# infrastructure/k8s/pdb.yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: settlement-service-pdb
  namespace: nexus-settlement
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app: settlement-service
```

---

## 6. Zero-downtime considerations

### Termination grace period

All deployments set `terminationGracePeriodSeconds: 30` so that in-flight HTTP
requests (P99 < 500ms) complete before a pod is removed.

```yaml
spec:
  template:
    spec:
      terminationGracePeriodSeconds: 30
      containers:
        - lifecycle:
            preStop:
              exec:
                command: ["sleep", "5"]   # Let the LB drain connections
```

### Kafka consumer rebalancing

Canary deployments add new consumer group members, triggering a rebalance.
During a rebalance (typically < 10 s), message processing pauses.

Mitigations:
- Use `session.timeout.ms = 10000` and `heartbeat.interval.ms = 3000`
- Set `max.poll.interval.ms` high enough to cover message processing time
- Monitor `kafka_consumer_group_lag` in Grafana; alert if lag spikes and does not recover within 60 s

### Readiness probes

Pods only receive traffic after the readiness probe succeeds. Ensure all services
define a proper readiness probe:

```yaml
readinessProbe:
  httpGet:
    path: /health
    port: 8001
  initialDelaySeconds: 10
  periodSeconds: 5
  failureThreshold: 3
```

---

## 7. Feature flags

Complex features that span multiple services (e.g. a new settlement flow that
requires both API gateway and settlement-service changes) should be gated
behind a feature flag to decouple deployment from release.

### Recommended approach

Store feature flags in the Vault KV store and read them at startup:

```bash
# Enable a flag for staging only
vault kv patch nexus/settlement-service \
  FEATURE_NEW_SETTLEMENT_FLOW=true

# Rolling restart to pick up the new flag value
kubectl -n nexus-staging rollout restart deployment/settlement-service
```

In code (`settlement-service/app/core/config.py`):

```python
class Settings(BaseSettings):
    feature_new_settlement_flow: bool = False
```

Flags default to `False` (disabled) so the old code path runs unless explicitly
enabled. This lets you deploy the new code to production weeks before enabling
the feature, and roll it back instantly by toggling the flag.
