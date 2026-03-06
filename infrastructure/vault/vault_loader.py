from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

VAULT_ADDR  = os.environ.get("VAULT_ADDR", "http://vault:8200")
VAULT_TOKEN = os.environ.get("VAULT_TOKEN", "")

_SECRET_MAP: list[tuple[str, str, str]] = [

    ("nexus/postgres",  "host",              "POSTGRES_HOST"),
    ("nexus/postgres",  "port",              "POSTGRES_PORT"),
    ("nexus/postgres",  "db",                "POSTGRES_DB"),
    ("nexus/postgres",  "user",              "POSTGRES_USER"),
    ("nexus/postgres",  "password",          "POSTGRES_PASSWORD"),
    ("nexus/redis",     "url",               "REDIS_URL"),
    ("nexus/redis",     "password",          "REDIS_PASSWORD"),
    ("nexus/jwt",       "private_key_base64","JWT_PRIVATE_KEY_BASE64"),
    ("nexus/jwt",       "public_key_base64", "JWT_PUBLIC_KEY_BASE64"),
    ("nexus/jwt",       "algorithm",         "JWT_ALGORITHM"),
    ("nexus/kafka",     "bootstrap_servers", "KAFKA_BOOTSTRAP_SERVERS"),
    ("nexus/aws",       "access_key_id",     "AWS_ACCESS_KEY_ID"),
    ("nexus/aws",       "secret_access_key", "AWS_SECRET_ACCESS_KEY"),
    ("nexus/aws",       "region",            "AWS_REGION"),
    ("nexus/aws",       "ses_from_email",    "SES_FROM_EMAIL"),
    ("nexus/twilio",    "account_sid",       "TWILIO_ACCOUNT_SID"),
    ("nexus/twilio",    "auth_token",        "TWILIO_AUTH_TOKEN"),
    ("nexus/twilio",    "from_number",       "TWILIO_FROM_NUMBER"),
]

def _fetch(path: str) -> dict[str, Any]:

    try:
        import httpx
    except ImportError:
        logger.warning("httpx not installed — cannot load secrets from Vault")
        return {}

    url = f"{VAULT_ADDR}/v1/{path}"
    headers = {"X-Vault-Token": VAULT_TOKEN}

    try:
        r = httpx.get(url, headers=headers, timeout=3.0)
        r.raise_for_status()
        return r.json().get("data", {}).get("data", {})
    except Exception as exc:
        logger.warning("Vault fetch failed for %s: %s", path, exc)
        return {}

def load_vault_secrets(overwrite: bool = False) -> None:

    if not VAULT_TOKEN:
        logger.debug("VAULT_TOKEN not set — skipping Vault secret loading")
        return

    cache: dict[str, dict[str, Any]] = {}

    for path, field, env_var in _SECRET_MAP:
        if not overwrite and env_var in os.environ:
            continue
        if path not in cache:
            cache[path] = _fetch(path)
        value = cache[path].get(field)
        if value is not None:
            os.environ[env_var] = str(value)
            logger.debug("Loaded %s from Vault (%s#%s)", env_var, path, field)

    logger.info("Vault secret loading complete (%d paths fetched)", len(cache))
