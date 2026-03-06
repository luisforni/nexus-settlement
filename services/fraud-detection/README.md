# Fraud Detection Service

Microservicio de detección de fraude en tiempo real. Implementado en **Python 3.12 + FastAPI**. Combina un modelo ensamblado **XGBoost + IsolationForest** con explicaciones **SHAP** para cada decisión.

---

## Responsabilidades

| Capa | Detalle |
|------|---------|
| **Scoring ML** | Predicción de riesgo [0.0, 1.0] con ensemble XGBoost + IsolationForest |
| **Decisión** | `APPROVE` (< 0.40) · `REVIEW` (0.40–0.75) · `BLOCK` (> 0.75) |
| **Explicabilidad** | SHAP values de las features de mayor impacto |
| **Degradación** | Sin artefacto de modelo → fallback a reglas estáticas (nunca falla el startup) |
| **Métricas** | `/metrics` Prometheus (FastAPI Instrumentator) |
| **Inferencia** | < 50 ms objetivo; modelo cargado en memoria una vez por proceso |

---

## Estructura

```
app/
├── main.py                              # Fábrica + lifespan (carga el modelo)
├── api/
│   └── v1/
│       ├── router.py
│       └── endpoints/
│           ├── fraud.py                 # Handlers: /score, /explain, /model-info
│           └── health.py
├── core/
│   ├── config.py                        # Pydantic Settings
│   └── logging.py
├── models/
│   ├── fraud_detector.py                # Wrapper ML: FraudDetector + ModelMetadata
│   └── feature_engineering.py          # Extracción/normalización de features
└── services/
    └── fraud_service.py                 # Lógica de score + llamada al detector
```

---

## API

### Health
```
GET /api/v1/fraud/health
```
```json
{"status": "ok", "service": "fraud-detection", "model_version": "untrained-v0"}
```

### Evaluar riesgo (score)
```
POST /api/v1/fraud/score
Content-Type: application/json

{
  "settlement_id": "uuid-v4",
  "amount": 250.00,
  "currency": "USD",
  "payer_id": "uuid-v4",
  "payee_id": "uuid-v4",
  "timestamp": "2026-03-06T00:00:00Z"   // opcional
}
```

Respuesta `200 OK`:
```json
{
  "settlement_id": "uuid-v4",
  "risk_score": 0.12,
  "decision": "APPROVE",
  "model_version": "v2.1.0",
  "scored_at": "2026-03-06T00:32:32Z"
}
```

### Explicación SHAP
```
GET /api/v1/fraud/explain/{settlement_id}
```
```json
{
  "settlement_id": "uuid-v4",
  "risk_score": 0.12,
  "decision": "APPROVE",
  "top_features": [
    {"name": "amount", "shap_value": 0.03},
    {"name": "hour_of_day", "shap_value": -0.01}
  ]
}
```

### Metadatos del modelo
```
GET /api/v1/fraud/model-info
```
```json
{
  "version": "v2.1.0",
  "model_type": "XGBoost+IsolationForest",
  "auc_roc": 0.97,
  "training_date": "2025-12-01",
  "feature_count": 18
}
```

---

## Modelo ML

### Arquitectura

```
Entrada (ScoreRequest)
       │
       ▼
Feature Engineering
  · normalización de amount
  · codificación de moneda
  · features temporales (hora, día semana)
  · frecuencia histórica payer/payee
       │
       ├──────────────────────────────┐
       ▼                              ▼
  XGBoost Classifier          IsolationForest
  (score supervisado)         (anomaly score)
       │                              │
       └──────────┬───────────────────┘
                  ▼
           Ensemble promedio
                  │
                  ▼
           risk_score [0,1]
                  │
                  ▼
         Umbrales de decisión:
           < 0.40 → APPROVE
         0.40–0.75 → REVIEW
           > 0.75 → BLOCK
```

### Artefacto del modelo

El modelo serializado se guarda en `/app/artifacts/fraud_model.joblib` (volumen Docker `fraud_model_artifacts`).

Estructura del artefacto:
```python
{
  "xgb": XGBClassifier,
  "isolation_forest": IsolationForest,
  "metadata": ModelMetadata
}
```

Si el archivo no existe en startup, el servicio arranca con un **modelo sin entrenar** que devuelve `risk_score=0.1` y `decision=APPROVE` para todas las peticiones.

### Entrenamiento

```bash
# (dentro del contenedor o con el venv activo)
python scripts/train_model.py \
  --data data/training_dataset.parquet \
  --output /app/artifacts/fraud_model.joblib
```

---

## Variables de entorno

| Variable | Obligatoria | Descripción |
|----------|:-----------:|-------------|
| `FRAUD_MODEL_PATH` | — | Ruta al artefacto (default: `/app/artifacts/fraud_model.joblib`) |
| `ENVIRONMENT` | — | `development` / `production` |
| `FRAUD_DETECTION_PORT` | — | Puerto de escucha (default: `8002`) |
| `KAFKA_BOOTSTRAP_SERVERS` | — | Brokers Kafka (para consumer de eventos futuros) |
| `CORS_ORIGINS` | — | Orígenes CORS permitidos |

---

## Desarrollo local

```bash
cd services/fraud-detection

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

uvicorn app.main:app --reload --port 8002
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
docker build --target development -t nexus-fraud-detection:dev .
docker build --target production  -t nexus-fraud-detection:prod .
```

Puerto `8002`, expuesto solo en loopback en desarrollo (`127.0.0.1:8002`).

---

## Documentación interactiva

Disponible en desarrollo:
- Swagger UI: http://localhost:8002/docs
- OpenAPI JSON: http://localhost:8002/openapi.json

Desactivada en `ENVIRONMENT=production`.

---

## Rendimiento

| Métrica | Objetivo |
|---------|---------|
| Latencia inferencia (P99) | < 50 ms |
| Startup model load | < 2 s |
| Throughput (instancia única) | ≥ 500 req/s |

El modelo es **read-only** tras la carga → thread-safe para peticiones concurrentes sin locks.

---

## Seguridad aplicada

| OWASP | Control |
|-------|---------|
| A03 — Injection | Pydantic `extra="forbid"` en todos los schemas de entrada |
| A05 — Misconfiguration | `/docs` desactivado en producción |
| A06 — Vulnerable Components | Dependabot + Bandit en CI; `pip audit` en Dockerfile |
| A09 — Logging | Errores internos no expuestos; structured JSON logs |
