# API Gateway

Punto de entrada único del sistema Nexus Settlement. Implementado en **Node.js 20 + Express + TypeScript**. Autentica, limita, valida y enruta todas las peticiones hacia los servicios internos.

---

## Responsabilidades

| Capa | Detalle |
|------|---------|
| **Autenticación** | JWT RS256 — verifica firma, expiración y algoritmo. Nunca acepta HS256. |
| **Autorización** | RBAC por scopes (`settlement:read`, `settlement:write`, `fraud:read`). |
| **Rate limiting** | Ventana deslizante por IP respaldada en Redis. 100 req/min por defecto. |
| **Validación** | Zod strict en el body de todas las mutaciones antes de hacer proxy. |
| **Proxy** | `http-proxy-middleware` con reescritura de path y reenvío de body. |
| **Circuit breaker** | Opossum — abre el circuito ante fallos sostenidos del upstream. |
| **Seguridad HTTP** | Helmet (CSP, HSTS, X-Frame-Options), CORS, HPP. |
| **Observabilidad** | Logs estructurados Pino con correlation ID (`X-Request-Id`). |

---

## Estructura

```
src/
├── app.ts                   # Entry point: middleware pipeline + servidor HTTP
├── config/
│   └── index.ts             # Variables de entorno con fail-fast (no hay hardcoding)
├── middleware/
│   ├── auth.ts              # JWT RS256 + RBAC (requireScope)
│   ├── logger.ts            # Pino HTTP logger + logger singleton
│   ├── rateLimiter.ts       # express-rate-limit + RedisStore
│   └── security.ts          # Helmet, CORS, HPP
└── routes/
    ├── health.ts            # GET /healthz  (sin auth)
    ├── settlements.ts       # Proxy a settlement-service + Zod + circuit breaker
    └── fraud.ts             # Proxy a fraud-detection
```

---

## Endpoints

### Healthcheck (público)
```
GET /healthz
```
Respuesta:
```json
{
  "status": "ok",
  "service": "api-gateway",
  "uptime_seconds": 42,
  "environment": "development"
}
```

### Settlements (requiere JWT)

| Método | Ruta | Scope | Headers adicionales |
|--------|------|-------|---------------------|
| `GET` | `/api/v1/settlements` | `settlement:read` | — |
| `GET` | `/api/v1/settlements/:id` | `settlement:read` | — |
| `POST` | `/api/v1/settlements` | `settlement:write` | `Idempotency-Key: <UUIDv4>` |
| `PATCH` | `/api/v1/settlements/:id/reverse` | `settlement:write` | `Idempotency-Key: <UUIDv4>` |

**Body de creación (POST)**:
```json
{
  "idempotency_key": "uuid-v4",
  "amount": 250.00,
  "currency": "USD",
  "payer_id": "uuid-v4",
  "payee_id": "uuid-v4",
  "metadata": {}
}
```

### Fraud Detection (requiere JWT)

| Método | Ruta | Scope |
|--------|------|-------|
| `POST` | `/api/v1/fraud/score` | `fraud:read` |
| `GET` | `/api/v1/fraud/explain/:settlement_id` | `fraud:read` |
| `GET` | `/api/v1/fraud/model-info` | `fraud:read` |

---

## Autenticación

El gateway usa **RS256** (asimétrico). Únicamente verifica con la clave pública; la clave privada nunca entra al contenedor del gateway.

### Generar token de prueba (desde el contenedor)

```bash
TOKEN=$(docker exec nexus-settlement-api-gateway-1 node -e \
  "const jwt=require('jsonwebtoken'),{randomUUID}=require('crypto');
   const k=Buffer.from(process.env.JWT_PRIVATE_KEY_BASE64,'base64').toString();
   process.stdout.write(jwt.sign(
     {sub:'test',scope:['settlement:read','settlement:write','fraud:read'],jti:randomUUID()},
     k,{algorithm:'RS256',expiresIn:'1h'}
   ));")
```

### Estructura del JWT

```json
{
  "sub": "user-uuid",
  "scope": ["settlement:read", "settlement:write", "fraud:read"],
  "jti": "uuid-v4-revocation-id",
  "iat": 1709000000,
  "exp": 1709003600
}
```

---

## Rate limiting

| Configuración | Valor por defecto | Variable de entorno |
|---------------|-------------------|---------------------|
| Ventana | 60 000 ms (1 min) | `RATE_LIMIT_WINDOW_MS` |
| Máx. solicitudes / IP | 100 | `RATE_LIMIT_MAX_REQUESTS` |
| Store | Redis (sliding window) | `REDIS_URL` |

Cuando se supera el límite devuelve:
```
HTTP 429 Too Many Requests
RateLimit-Remaining: 0
RateLimit-Reset: <epoch>
```

---

## Circuit breaker (settlement-service)

Implementado con [Opossum](https://nodeshift.dev/opossum/).

| Parámetro | Valor | Variable |
|-----------|-------|----------|
| Timeout por petición | 3 000 ms | `CB_TIMEOUT_MS` |
| Umbral de error | 50 % | `CB_ERROR_THRESHOLD_PCT` |
| Tiempo de reset | 30 000 ms | `CB_RESET_TIMEOUT_MS` |

Estados: **CLOSED** → **OPEN** → **HALF-OPEN** → CLOSED

---

## Variables de entorno

| Variable | Obligatoria | Descripción |
|----------|:-----------:|-------------|
| `JWT_PUBLIC_KEY_BASE64` | ✅ | PEM de clave pública RSA-2048 en base64 |
| `SETTLEMENT_SERVICE_URL` | ✅ | URL interna del settlement-service |
| `FRAUD_DETECTION_URL` | ✅ | URL interna del fraud-detection |
| `NOTIFICATION_SERVICE_URL` | ✅ | URL interna del notification-service |
| `REDIS_URL` | ✅ | DSN de Redis (para rate-limit) |
| `API_GATEWAY_PORT` | — | Puerto de escucha (default: `3000`) |
| `RATE_LIMIT_WINDOW_MS` | — | Ventana del rate-limit en ms (default: `60000`) |
| `RATE_LIMIT_MAX_REQUESTS` | — | Máx. req/IP/ventana (default: `100`) |
| `CORS_ALLOWED_ORIGINS` | — | Orígenes permitidos, separados por coma |
| `CB_TIMEOUT_MS` | — | Timeout circuit breaker (default: `3000`) |
| `CB_ERROR_THRESHOLD_PCT` | — | Umbral de apertura en % (default: `50`) |
| `CB_RESET_TIMEOUT_MS` | — | Pausa antes de HALF-OPEN (default: `30000`) |

---

## Desarrollo local

```bash
cd services/api-gateway
npm install
npm run dev      # ts-node-dev con hot-reload
```

### Tests

```bash
npm test         # Jest
npm run lint     # ESLint + Prettier
npm run build    # tsc → dist/
```

---

## Docker

```dockerfile
# Multi-stage: development (ts-node-dev) | production (compilado)
docker build --target development -t nexus-api-gateway:dev .
docker build --target production  -t nexus-api-gateway:prod .
```

El contenedor expone el puerto `3000`. En `docker-compose.yml` se mapea a `4000` en el host.

---

## Seguridad aplicada

| OWASP | Control |
|-------|---------|
| A01 — Broken Access Control | `requireScope()` en cada ruta; deniega por defecto |
| A02 — Cryptographic Failures | RS256 obligatorio; HS256 rechazado explícitamente |
| A03 — Injection | Validación Zod antes del proxy; `strict: true` en JSON parser |
| A04 — Insecure Design | `Idempotency-Key` obligatorio en mutaciones |
| A05 — Security Misconfiguration | Helmet, CORS, `docs_url=None` en producción |
| A07 — Auth Failures | JWT verificado con clave pública; mensaje de error genérico (no oracle) |
| A09 — Logging Failures | Errores 5xx loggeados internamente; cliente recibe solo "Internal Server Error" |
