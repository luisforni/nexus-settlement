from __future__ import annotations

import argparse
import asyncio
import random
import sys
import uuid
from datetime import datetime, timezone

import httpx

try:
    from rich.console import Console
    from rich.table import Table

    RICH = True
except ImportError:
    RICH = False

DEFAULT_GATEWAY_URL = "http://localhost:8001"

CURRENCIES = ["USD", "EUR", "GBP", "JPY", "BRL", "SGD", "AED"]

DEMO_SETTLEMENTS = [
    {
        "payer_id": str(uuid.uuid4()),
        "payee_id": str(uuid.uuid4()),
        "amount": f"{random.uniform(1_000, 500_000):.2f}",
        "currency": random.choice(CURRENCIES),
    }
    for i in range(20)
]

DEMO_SETTLEMENTS += [
    {
        "payer_id": str(uuid.uuid4()),
        "payee_id": str(uuid.uuid4()),
        "amount": "9999999.00",
        "currency": "USD",
    },
    {
        "payer_id": str(uuid.uuid4()),
        "payee_id": str(uuid.uuid4()),
        "amount": "0.01",
        "currency": "EUR",
    },
]

def _idempotency_key() -> str:
    return str(uuid.uuid4())

async def seed(gateway_url: str) -> None:
    console = Console() if RICH else None

    headers = {
        "Content-Type": "application/json",
    }

    results: list[dict] = []

    async with httpx.AsyncClient(base_url=gateway_url, timeout=10.0) as client:
        for i, payload in enumerate(DEMO_SETTLEMENTS):

            idem_key = _idempotency_key()
            headers["Idempotency-Key"] = idem_key
            body = {**payload, "idempotency_key": idem_key}

            try:
                resp = await client.post("/api/v1/settlements", json=body, headers=headers)
                if resp.status_code in (200, 201):
                    body = resp.json()
                    results.append(
                        {
                            "index": i + 1,
                            "id": body.get("id", "?"),
                            "amount": payload["amount"],
                            "currency": payload["currency"],
                            "status": "✓ created",
                        }
                    )
                else:
                    results.append(
                        {
                            "index": i + 1,
                            "id": "-",
                            "amount": payload["amount"],
                            "currency": payload["currency"],
                            "status": f"✗ {resp.status_code}",
                        }
                    )
            except httpx.RequestError as exc:
                results.append(
                    {
                        "index": i + 1,
                        "id": "-",
                        "amount": payload["amount"],
                        "currency": payload["currency"],
                        "status": f"✗ {exc!r}",
                    }
                )

    if RICH and console:
        table = Table(title="Seed Results", show_lines=True)
        table.add_column("#", style="dim")
        table.add_column("Settlement ID")
        table.add_column("Amount")
        table.add_column("Currency")
        table.add_column("Status")

        for r in results:
            colour = "green" if "✓" in r["status"] else "red"
            table.add_row(
                str(r["index"]),
                r["id"],
                r["amount"],
                r["currency"],
                f"[{colour}]{r['status']}[/{colour}]",
            )
        console.print(table)
    else:
        for r in results:
            ts = datetime.now(timezone.utc).isoformat()
            print(f"[{ts}] #{r['index']} {r['status']} — {r['amount']} {r['currency']}")

    ok = sum(1 for r in results if "✓" in r["status"])
    fail = len(results) - ok
    print(f"\n{ok} created, {fail} failed.")
    if fail > 0:
        sys.exit(1)

def main() -> None:
    parser = argparse.ArgumentParser(description="Seed demo settlements into nexus-settlement")
    parser.add_argument(
        "--url",
        default=DEFAULT_GATEWAY_URL,
        help=f"API Gateway base URL (default: {DEFAULT_GATEWAY_URL})",
    )
    args = parser.parse_args()
    asyncio.run(seed(args.url))

if __name__ == "__main__":
    main()
