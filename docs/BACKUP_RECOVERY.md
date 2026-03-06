# PostgreSQL Backup & Recovery

**Document owner**: Platform Engineering
**Scope**: `nexus_settlement` database (PostgreSQL 15)

---

## Table of Contents

1. [Backup architecture](#1-backup-architecture)
2. [Backup schedule](#2-backup-schedule)
3. [Full database dump (pg_dump)](#3-full-database-dump-pg_dump)
4. [Continuous WAL archiving and PITR](#4-continuous-wal-archiving-and-pitr)
5. [AWS RDS automated backups](#5-aws-rds-automated-backups)
6. [Restoration procedures](#6-restoration-procedures)
7. [Disaster recovery](#7-disaster-recovery)
8. [Backup verification](#8-backup-verification)
9. [Recovery time and point objectives](#9-recovery-time-and-point-objectives)

---

## 1. Backup architecture

```
┌─────────────────────┐        ┌───────────────────────┐
│  PostgreSQL 15      │        │   S3 (encrypted)      │
│  nexus_settlement   │──WAL──▶│   nexus-pg-wal-archive│
│                     │        │                       │
│  (Kubernetes PVC or │──dump──▶  nexus-pg-backups     │
│   AWS RDS)          │        └───────────────────────┘
└─────────────────────┘                 │
                                        ▼
                                ┌───────────────────────┐
                                │  Cross-region replica  │
                                │  (us-west-2)           │
                                └───────────────────────┘
```

- **Logical backups**: `pg_dump` compressed snapshots uploaded to `s3://nexus-pg-backups/`
- **Physical backups**: WAL archiving to `s3://nexus-pg-wal-archive/` enabling point-in-time recovery (PITR)
- **All backups encrypted**: AES-256 server-side encryption (KMS key `alias/nexus-pg-backups`)
- **Cross-region replication**: enabled on both S3 buckets for DR

---

## 2. Backup schedule

| Backup type | Frequency | Retention | Storage class |
|-------------|-----------|-----------|---------------|
| Full dump (`pg_dump`) | Daily 02:00 UTC | 30 days | S3 Standard-IA |
| WAL segment archive | Continuous (every 5 min or 16 MB) | 7 days | S3 Standard |
| Weekly full dump | Sundays 01:00 UTC | 12 weeks | S3 Glacier |
| RDS automated snapshot (prod) | Daily | 35 days | RDS managed |

---

## 3. Full database dump (pg_dump)

### Manual dump

```bash
# Run from inside the cluster (using the settlement-service image for psql tools)
kubectl -n nexus-settlement run --rm -it pg-backup \
  --image=postgres:15-alpine \
  --restart=Never \
  --env="PGPASSWORD=$POSTGRES_PASSWORD" \
  -- pg_dump \
    --host=postgres \
    --port=5432 \
    --username=nexus \
    --dbname=nexus_settlement \
    --format=custom \
    --compress=9 \
    --file=/tmp/nexus_settlement_$(date +%F_%H%M%S).dump

# Copy the dump out of the pod
kubectl cp nexus-settlement/pg-backup:/tmp/nexus_settlement_*.dump ./backups/
```

### Automated daily backup (CronJob)

```yaml
# infrastructure/k8s/pg-backup-cronjob.yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: pg-daily-backup
  namespace: nexus-settlement
spec:
  schedule: "0 2 * * *"
  concurrencyPolicy: Forbid
  jobTemplate:
    spec:
      template:
        spec:
          restartPolicy: OnFailure
          containers:
            - name: pg-backup
              image: postgres:15-alpine
              env:
                - name: PGPASSWORD
                  valueFrom:
                    secretKeyRef:
                      name: nexus-db-credentials
                      key: password
                - name: S3_BUCKET
                  value: nexus-pg-backups
              command:
                - /bin/sh
                - -c
                - |
                  FILENAME="nexus_settlement_$(date +%F_%H%M%S).dump"
                  pg_dump --host=postgres --port=5432 --username=nexus \
                    --dbname=nexus_settlement --format=custom --compress=9 \
                    --file="/tmp/$FILENAME"
                  aws s3 cp "/tmp/$FILENAME" \
                    "s3://$S3_BUCKET/daily/$FILENAME" \
                    --sse aws:kms --sse-kms-key-id alias/nexus-pg-backups
              resources:
                requests:
                  cpu: 100m
                  memory: 256Mi
                limits:
                  cpu: 500m
                  memory: 512Mi
```

```bash
kubectl apply -f infrastructure/k8s/pg-backup-cronjob.yaml
```

---

## 4. Continuous WAL archiving and PITR

### Enable WAL archiving in postgresql.conf

```ini
# /etc/postgresql/postgresql.conf (or RDS parameter group)
wal_level = replica
archive_mode = on
archive_command = 'aws s3 cp %p s3://nexus-pg-wal-archive/wal/%f --sse aws:kms'
archive_timeout = 300       # Force archive every 5 minutes even without 16MB
```

### Verify archiving is working

```sql
-- Connect to the database
SELECT pg_switch_wal();                    -- Force a WAL switch
SELECT * FROM pg_stat_archiver;           -- Should show last_archived_time recently
```

### Point-in-time recovery (PITR)

PITR is used to recover to a specific timestamp before an incident.

```bash
# 1. Identify the base backup to restore from
aws s3 ls s3://nexus-pg-backups/daily/ --recursive | sort | tail -5

# 2. Restore the base backup to a recovery instance
aws s3 cp s3://nexus-pg-backups/daily/nexus_settlement_2026-03-09_020000.dump \
  /tmp/base.dump

pg_restore \
  --host=postgres-recovery \
  --port=5432 \
  --username=nexus \
  --dbname=nexus_settlement_recovery \
  --format=custom \
  --jobs=4 \
  /tmp/base.dump

# 3. Write the recovery configuration
cat > /var/lib/postgresql/data/recovery.conf << 'EOF'
restore_command = 'aws s3 cp s3://nexus-pg-wal-archive/wal/%f %p'
recovery_target_time = '2026-03-10 14:30:00 UTC'   # Target: just before the incident
recovery_target_action = 'promote'
EOF

# 4. Start PostgreSQL — it will replay WAL segments until the target time
pg_ctl start -D /var/lib/postgresql/data

# 5. Verify data consistency before promoting
psql -U nexus -d nexus_settlement_recovery -c "SELECT count(*) FROM settlements;"
```

---

## 5. AWS RDS automated backups

When deployed on RDS (production AWS), automated snapshots are enabled.

```hcl
# infrastructure/terraform/modules/rds/main.tf (excerpt)
resource "aws_db_instance" "nexus" {
  backup_retention_period        = 35
  backup_window                  = "02:00-03:00"
  maintenance_window             = "sun:04:00-sun:05:00"
  deletion_protection            = true
  skip_final_snapshot            = false
  final_snapshot_identifier      = "nexus-settlement-final"
  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]
}
```

### Restore RDS snapshot

```bash
# List available snapshots
aws rds describe-db-snapshots \
  --db-instance-identifier nexus-settlement-prod \
  --query 'DBSnapshots[*].[DBSnapshotIdentifier,SnapshotCreateTime,Status]' \
  --output table

# Restore to a new instance
aws rds restore-db-instance-from-db-snapshot \
  --db-instance-identifier nexus-settlement-recovery \
  --db-snapshot-identifier rds:nexus-settlement-prod-2026-03-09 \
  --db-instance-class db.r7g.large \
  --no-publicly-accessible

# Wait for the instance to be available
aws rds wait db-instance-available \
  --db-instance-identifier nexus-settlement-recovery
```

### RDS point-in-time restore

```bash
aws rds restore-db-instance-to-point-in-time \
  --source-db-instance-identifier nexus-settlement-prod \
  --target-db-instance-identifier nexus-settlement-pitr \
  --restore-time 2026-03-10T14:30:00Z \
  --db-instance-class db.r7g.large
```

---

## 6. Restoration procedures

### Scenario A: Accidental table DROP or bulk DELETE

**Recovery time target:** < 30 minutes

```bash
# 1. Identify the time of the incident from application logs / Prometheus
# 2. Create a recovery instance from the last daily dump + WAL replay to T-2min

# 3. Extract only the affected table from the recovery instance
pg_dump \
  --host=postgres-recovery \
  --username=nexus \
  --dbname=nexus_settlement_recovery \
  --table=settlements \
  --format=custom \
  --file=/tmp/settlements_recovered.dump

# 4. Restore the table into production (CAREFUL: wrap in a transaction)
psql --host=postgres --username=nexus --dbname=nexus_settlement << 'EOF'
BEGIN;
-- Rename the broken table (as a failsafe)
ALTER TABLE settlements RENAME TO settlements_broken;
EOF

pg_restore \
  --host=postgres \
  --username=nexus \
  --dbname=nexus_settlement \
  --table=settlements \
  --format=custom \
  /tmp/settlements_recovered.dump

# 5. Verify row counts, then commit
psql --host=postgres --username=nexus --dbname=nexus_settlement \
  -c "SELECT count(*) FROM settlements;"

# 6. Drop the broken backup table after verification
psql --host=postgres --username=nexus --dbname=nexus_settlement \
  -c "DROP TABLE settlements_broken;"
```

### Scenario B: Full database corruption

**Recovery time target:** < 2 hours

```bash
# 1. Stop settlement-service to prevent writes
kubectl -n nexus-settlement scale deployment/settlement-service --replicas=0

# 2. Restore from the latest daily dump + WAL replay (full PITR, see §4)

# 3. Point the service to the new database endpoint
kubectl -n nexus-settlement patch configmap nexus-config \
  -p '{"data":{"POSTGRES_HOST":"postgres-recovery"}}'

# 4. Scale the service back up
kubectl -n nexus-settlement scale deployment/settlement-service --replicas=3

# 5. Verify health
curl -fs https://api.nexus-settlement.example.com/health | jq .
```

---

## 7. Disaster recovery

### Region failover

In a full region failure, the recovery target is the cross-region replica.

```bash
# 1. Promote the Read Replica in us-west-2
aws rds promote-read-replica \
  --db-instance-identifier nexus-settlement-replica-us-west-2

# 2. Update DNS / Terraform variables to point at the secondary region endpoint
# infrastructure/terraform/envs/prod/terraform.tfvars
#   db_host = "nexus-settlement-replica-us-west-2.xxxxx.us-west-2.rds.amazonaws.com"

terraform apply -var-file=envs/prod/terraform.tfvars

# 3. Deploy services to the secondary EKS cluster
argocd cluster add <secondary-cluster-context>
argocd app set nexus-settlement \
  --dest-server https://<secondary-cluster-api>:443

argocd app sync nexus-settlement
```

---

## 8. Backup verification

Backups must be tested monthly to ensure they are restorable.

```bash
#!/usr/bin/env bash
# scripts/verify-backup.sh

set -euo pipefail

BUCKET="nexus-pg-backups"
LATEST=$(aws s3 ls "s3://$BUCKET/daily/" | sort | tail -1 | awk '{print $4}')

echo "Testing restore of: $LATEST"
aws s3 cp "s3://$BUCKET/daily/$LATEST" /tmp/test.dump

# Spin up a temporary PostgreSQL container
docker run --rm -d \
  --name pg-verify \
  -e POSTGRES_USER=nexus \
  -e POSTGRES_PASSWORD=verify \
  -e POSTGRES_DB=nexus_test \
  -p 15432:5432 \
  postgres:15-alpine

sleep 5

pg_restore \
  --host=localhost --port=15432 \
  --username=nexus --dbname=nexus_test \
  /tmp/test.dump

ROW_COUNT=$(psql -h localhost -p 15432 -U nexus -d nexus_test \
  -t -c "SELECT count(*) FROM settlements;")

echo "Row count in settlements: $ROW_COUNT"

docker stop pg-verify

if [[ "$ROW_COUNT" -gt 0 ]]; then
  echo "BACKUP VERIFICATION PASSED"
else
  echo "BACKUP VERIFICATION FAILED — settlements table is empty"
  exit 1
fi
```

---

## 9. Recovery time and point objectives

| Metric | Target |
|--------|--------|
| **RTO** (Recovery Time Objective) | < 2 hours for full region failure |
| **RTO** (single table / row data) | < 30 minutes |
| **RPO** (Recovery Point Objective) | < 5 minutes (WAL archiving interval) |
| Backup verification | Monthly automated restore test |
| DR drill | Quarterly full failover exercise |
