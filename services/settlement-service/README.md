# Settlement Service

Microservicio de liquidaciones financieras. Implementado en **Python 3.12 + FastAPI + SQLAlchemy async**. Gestiona el ciclo de vida completo de un settlement: creación, idempotencia, máquina de estados, publicación de eventos Kafka y métricas Prometheus.

---

## Responsabilidades

| Capa | Detalle |
|------|---------|
| **API REST** | CRUD completo de settlements (Pydantic v2, FastAPI) |
| **Idempotencia** | Clave UUID v4 única por operación — evita duplicados ante reintentos |
| **Máquina de estados** | `PENDING → PROCESSING → COMPLETED / FAILED → REVERSED` |
| **Persistencia** | PostgreSQL 16 vía asyncpg + SQLAlchemy async ORM |
| **Mensajería** | Publica `settlement.created` en `nexus.settlements` (aiokafka, acks=all) |
| **Métricas** | `/metrics` endpoint (Prometheus FastAPI Instrumentator) |
| **Seguridad** | Validación estricta de entrada; no expone errores internos |

---

## Estructura

```
app/
├── main.py                         # Fábrica de aplicación + lifespan (Kafka, DB)
├── api/
│   └── v1/
│       ├── router.py               # Agrupación de routers v1
│       └── endpoints/
│           ├── settlements.py      # Handlers HTTP (GET, POST, PATCH /reverse)
│           └── health.py           # GET /api/v1/health
├── core/
│   ├── config.py                   # Pydantic Settings (fail-fast en startup)
│   └── logging.py                  # Structured JSON logger
├── db/
│   ├── base.py                     # DeclarativeBase SQLAlchemy
│   └── session.py                  # Engine async + SessionLocal
├── models/
│   └── settlement.py               # ORM Settlement + SettlementStatus enum
├── schemas/
│   └── settlement.py               # Pydantic v2 schemas (Request / Response)
├── services/
│   └── settlement_service.py       # Lógica de negocio + repositorio
└── messaging/
    └── kafka_producer.py           # KafkaProducer wrapper (aiokafka)
```

---

## API

### Health
```
GET /api/v1/health
```
```json
{"status": "ok", "service": "settlement-service"}
```

### Listar settlements
```
GET /api/v1/settlements?page=1&page_size=20&status=PENDING
```
```json
{
  "items": [...],
  "total": 42,
  "page": 1,
  "page_size": 20
}
```

### Crear settlement
```
POST /api/v1/settlements
Content-Type: application/json
Idempotency-Key: <UUIDv4>

{
  "idempotency_key": "uuid-v4",
  "amount": 250.00,
  "currency": "USD",
  "payer_id": "uuid-v4",
  "payee_id": "uuid-v4"
}
```
- Responde `201 Created` con el objeto completo.
- Si se repite el mismo `idempotency_key`, devuelve `201` con el registro original (sin crear duplicado).

### Obtener por ID
```
GET /api/v1/settlements/{settlement_id}
```

### Revertir
```
PATCH /api/v1/settlements/{settlement_id}/reverse
Idempotency-Key: <UUIDv4>
```
Solo aplicable a settlements en estado `COMPLETED`. Transiciona a `REVERSED`.

---

## Modelo de datos

```
settlements
├── id                UUID        PK, gen_random_uuid()
├── idempotency_key   UUID        UNIQUE NOT NULL
├── status            ENUM        PENDING | PROCESSING | COMPLETED | FAILED | REVERSED
├── amount            NUMERIC(20,4)   > 0
├── currency          CHAR(3)     ISO 4217
├── payer_id          UUID        NOT NULL
├── payee_id          UUID        NOT NULL
├── risk_score        FLOAT       nullable (set by fraud-detection)
├── failure_reason    TEXT        nullable
├── version           INT         optimistic locking
├── created_at        TIMESTAMPTZ NOT NULL
├── updated_at        TIMESTAMPTZ NOT NULL
└── deleted_at        TIMESTAMPTZ nullable (soft delete)
```

**Índices**:
- `uq_settlements_idempotency_key` — unicidad de idempotencia
- `ix_settlements_status_created` — búsquedas por estado/fecha (parcial, `deleted_at IS NULL`)
- `ix_settlements_payer_id`, `ix_settlements_payee_id`

---

## Máquina de estados

```
              ┌─────────┐
  inicio ────►│ PENDING │
              └────┬────┘
                   │ procesando
              ┌────▼──────────┐
              │  PROCESSING   │
              └────┬──────────┘
          ┌────────┴──────────┐
     ┌────▼────┐          ┌───▼───┐
     │COMPLETED│          │ FAILED│ (terminal)
     └────┬────┘          └───────┘
          │ reverso
     ┌────▼────┐
     │REVERSED │ (terminal)
     └─────────┘
```

Transiciones inválidas devuelven `HTTP 409 Conflict`.

---

## Eventos Kafka

Tras una creación exitosa, publica en el topic `nexus.settlements`:

```json
{
  "schema_version": "1.0",
  "published_at": "2026-03-06T00:08:52Z",
  "payload": {
    "event": "settlement.created",
    "settlement_id": "uuid",
    "idempotency_key": "uuid",
    "amount": "250.0000",
    "currency": "USD",
    "payer_id": "uuid",
    "payee_id": "uuid",
    "requesting_user_id": "uuid",
    "timestamp": "2026-03-06T00:08:52Z"
  },
  "sha256": "<hex-hash-del-payload>"
}
```

El productor usa `acks='all'` + `enable_idempotence=True` para garantías de entrega exactamente-una-vez.

---

## Variables de entorno

| Variable | Obligatoria | Descripción |
|----------|:-----------:|-------------|
| `POSTGRES_HOST` | ✅ | Host de PostgreSQL |
| `POSTGRES_PORT` | — | Puerto (default: `5432`) |
| `POSTGRES_DB` | ✅ | Nombre de la base de datos |
| `POSTGRES_USER` | ✅ | Usuario |
| `POSTGRES_PASSWORD` | ✅ | Contraseña |
| `REDIS_URL` | ✅ | DSN de Redis |
| `KAFKA_BOOTSTRAP_SERVERS` | ✅ | Brokers Kafka (`kafka:29092`) |
| `KAFKA_TOPIC_SETTLEMENTS` | — | Topic de eventos (default: `nexus.settlements`) |
| `JWT_PUBLIC_KEY_BASE64` | ✅ | PEM pública RSA-2048 en base64 |
| `ENVIRONMENT` | — | `development` / `staging` / `production` |
| `SETTLEMENT_SERVICE_PORT` | — | Puerto de escucha (default: `8001`) |
| `SETTLEMENT_WORKERS` | — | Uvicorn workers (default: `4`) |
| `SETTLEMENT_MAX_AMOUNT` | — | Monto máximo permitido (default: `10000000.0`) |

---

## Desarrollo local

```bash
cd services/settlement-service

# Entorno virtual
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Ejecutar (requiere Postgres + Kafka + Redis corriendo)
uvicorn app.main:app --reload --port 8001
```

### Tests

```bash
pytest tests/ -v
pytest tests/ --cov=app --cov-report=term-missing
```

### Linting

```bash
ruff check app/
black --check app/
mypy app/
```

---

## Docker

```bash
# Desarrollo (hot-reload con volúmenes montados)
docker build --target development -t nexus-settlement-svc:dev .

# Producción (imagen mínima)
docker build --target production  -t nexus-settlement-svc:prod .
```

El contenedor expone el puerto `8001`. En desarrollo, está expuesto solo en loopback (`127.0.0.1:8001`).

---

## Documentación interactiva

Disponible en desarrollo:
- Swagger UI: http://localhost:8001/docs
- ReDoc: http://localhost:8001/redoc
- OpenAPI JSON: http://localhost:8001/openapi.json

Desactivada en `ENVIRONMENT=production`.

---

## Seguridad aplicada

| OWASP | Control |
|-------|---------|
| A03 — Injection | SQLAlchemy ORM parametrizado; Pydantic `extra="forbid"` |
| A04 — Insecure Design | `idempotency_key` UUID v4 obligatorio; `amount > 0` con CHECK constraint |
| A05 — Misconfiguration | `/docs` desactivado en producción; `TrustedHostMiddleware` activo |
| A08 — Integrity Failures | SHA-256 en cada mensaje Kafka; `version` para locking optimista |
| A09 — Logging Failures | Errores internos loggeados, no expuestos; sin stack traces al cliente |
