# infrastructure/vault/policy-notification.hcl
# Vault policy for the notification-service.

path "nexus/data/kafka" {
  capabilities = ["read"]
}

path "nexus/data/aws" {
  capabilities = ["read"]
}

path "nexus/data/twilio" {
  capabilities = ["read"]
}
