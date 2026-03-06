-- PostgreSQL initialisation: extensions + role setup.
-- This script runs once when the Docker volume is first created.
-- Referenced by docker-compose.yml (./infrastructure/postgres/init:/docker-entrypoint-initdb.d).

-- ── Extensions ────────────────────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";    -- uuid_generate_v4()
CREATE EXTENSION IF NOT EXISTS "pgcrypto";     -- gen_random_uuid(), crypt(), etc.
CREATE EXTENSION IF NOT EXISTS "pg_trgm";      -- trigram indexes for fuzzy search

-- ── Schemas ───────────────────────────────────────────────────────────────────
CREATE SCHEMA IF NOT EXISTS settlements;
CREATE SCHEMA IF NOT EXISTS audit;

-- ── Application role (least-privilege, OWASP A01) ─────────────────────────────
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nexus_app') THEN
    CREATE ROLE nexus_app WITH LOGIN PASSWORD 'CHANGE_ME_IN_ENV';
  END IF;
END
$$;

-- Grant schema usage
GRANT USAGE ON SCHEMA settlements TO nexus_app;
GRANT USAGE ON SCHEMA audit       TO nexus_app;

-- Table privileges will be granted after migrations run (Alembic creates tables).
-- Pre-grant default privileges for future tables so app role gains access automatically.
ALTER DEFAULT PRIVILEGES IN SCHEMA settlements
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO nexus_app;

ALTER DEFAULT PRIVILEGES IN SCHEMA settlements
  GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO nexus_app;

ALTER DEFAULT PRIVILEGES IN SCHEMA audit
  GRANT SELECT, INSERT ON TABLES TO nexus_app;

-- ── Audit log table ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit.events (
  id          BIGSERIAL    PRIMARY KEY,
  occurred_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  actor_id    UUID,
  event_type  TEXT         NOT NULL,
  resource    TEXT         NOT NULL,
  resource_id UUID,
  old_value   JSONB,
  new_value   JSONB,
  ip_address  INET,
  user_agent  TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_events_resource_id  ON audit.events (resource_id);
CREATE INDEX IF NOT EXISTS idx_audit_events_actor_id     ON audit.events (actor_id);
CREATE INDEX IF NOT EXISTS idx_audit_events_occurred_at  ON audit.events (occurred_at);
