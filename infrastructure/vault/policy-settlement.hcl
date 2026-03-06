# infrastructure/vault/policy-settlement.hcl
# Vault policy for the settlement-service.
# Grant read-only access to the secrets it needs.

path "nexus/data/postgres" {
  capabilities = ["read"]
}

path "nexus/data/redis" {
  capabilities = ["read"]
}

path "nexus/data/jwt" {
  capabilities = ["read"]
}

path "nexus/data/kafka" {
  capabilities = ["read"]
}
