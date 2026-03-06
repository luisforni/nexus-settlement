"""

  - name: nexus-teammaintainers:home: https://github.com/example/nexus-settlement  - microservices  - payments  - settlement  - fintechkeywords:appVersion: "1.0.0"version: 0.1.0type: applicationdescription: Nexus Settlement — distributed financial settlement microservices platformscripts/export_openapi.py
Export OpenAPI specs from all FastAPI services to shared/contracts/.

Usage:
    # Minimal required env vars (service imports need them at module load):
    POSTGRES_HOST=localhost POSTGRES_DB=x POSTGRES_USER=x POSTGRES_PASSWORD=x \\
    REDIS_URL=redis://localhost KAFKA_BOOTSTRAP_SERVERS=localhost:9092 \\
    JWT_PUBLIC_KEY_BASE64=dGVzdA== python scripts/export_openapi.py

Output:
    shared/contracts/openapi-settlement-service.json
    shared/contracts/openapi-fraud-detection.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

def export_service(service_dir: str, app_import: str, output_name: str) -> None:
    service_path = REPO_ROOT / "services" / service_dir
    sys.path.insert(0, str(service_path))
    try:
        import importlib
        module_parts = app_import.rsplit(".", 1)
        mod = importlib.import_module(module_parts[0])
        app = getattr(mod, module_parts[1])
        spec = app.openapi()
        out_path = REPO_ROOT / "shared" / "contracts" / output_name
        out_path.write_text(json.dumps(spec, indent=2))
        print(f"  ✓ {output_name}")
    except Exception as exc:
        print(f"  ✗ {output_name}: {exc}", file=sys.stderr)
    finally:
        sys.path.pop(0)

if __name__ == "__main__":
    print("Exporting OpenAPI specs...")
    export_service("settlement-service", "app.main.app",    "openapi-settlement-service.json")
    export_service("fraud-detection",    "app.main.app",    "openapi-fraud-detection.json")
    print("Done — specs written to shared/contracts/")
