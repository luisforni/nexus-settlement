# Notification Service

Servicio de notificaciones asíncronas. Implementado en **Node.js 20 + KafkaJS + TypeScript**. Consume eventos de settlement y fraude desde Kafka y los despacha a través de email, SMS o webhook según el tipo de evento.

---

## Responsabilidades

| Capa | Detalle |
|------|---------|
| **Consumer Kafka** | Suscrito a `nexus.settlements`, `nexus.fraud.alerts`, `nexus.notifications` |
| **Validación** | Zod valida el envelope y el payload antes de procesar (OWASP A03) |
| **Routing** | Despacha al canal correcto según `event_type` |
| **Canales** | Email (SES / SMTP), SMS (Twilio), Webhook (HTTP POST) |
| **Salud** | Servidor HTTP mínimo en `/health` para Docker healthcheck |
| **Graceful shutdown** | Desconecta consumer Kafka antes de salir (`SIGTERM`/`SIGINT`) |

---

## Estructura

```
src/
├── app.ts                           # Entry point: consumer Kafka + servidor HTTP
├── config.ts                        # Variables de entorno tipadas
├── logger.ts                        # Pino structured logger
├── handlers/
│   └── notification.handler.ts      # Router de eventos + lógica de despacho
└── channels/
    ├── email.ts                     # Envío de email (SES / SMTP / mock dev)
    ├── sms.ts                       # Envío de SMS (Twilio / mock dev)
    └── webhook.ts                   # HTTP POST a URL externa
```

---

## Topics Kafka consumidos

| Topic | Eventos procesados |
|-------|--------------------|
| `nexus.settlements` | `settlement.created`, `settlement.completed`, `settlement.failed`, `settlement.reversed` |
| `nexus.fraud.alerts` | `fraud.review`, `fraud.blocked` |
| `nexus.notifications` | `notification.send` (genérico) |

---

## Envelope de mensaje Kafka esperado

Todos los mensajes deben cumplir este schema (validado con Zod):

```json
{
  "event_id": "uuid-v4",
  "event_type": "settlement.completed",
  "timestamp": "2026-03-06T00:10:00Z",
  "payload": { ... },
  "integrity_hash": "sha256-hex-opcional"
}
```

Mensajes que no cumplen el schema son **descartados** (logged y no comiteados como error).

---

## Routing de eventos

| `event_type` | Acción |
|---|---|
| `settlement.completed` | Email + SMS + Webhook al usuario |
| `settlement.failed` | Email de alerta al usuario |
| `fraud.review` | Email + Webhook al equipo de revisión |
| `fraud.blocked` | Email + Webhook (urgente) al equipo de riesgo |
| `notification.send` | Canal determinado por `payload.channel` (`email`/`sms`/`webhook`) |

---

## Servidor HTTP de salud

```
GET /health    →  200 { "status": "ok" }    (cuando el consumer está corriendo)
               →  503 { "status": "starting" } (durante boot)

GET /livez     →  alias de /health
```

---

## Variables de entorno

| Variable | Obligatoria | Descripción |
|----------|:-----------:|-------------|
| `KAFKA_BROKERS` | ✅ | Brokers separados por coma (`kafka:29092`) |
| `KAFKA_GROUP_ID` | — | Consumer group ID (default: `notification-service`) |
| `KAFKA_TOPIC_SETTLEMENTS` | — | Topic de settlements (default: `nexus.settlements`) |
| `KAFKA_TOPIC_FRAUD_ALERTS` | — | Topic de alertas de fraude (default: `nexus.fraud.alerts`) |
| `KAFKA_TOPIC_NOTIFICATIONS` | — | Topic genérico (default: `nexus.notifications`) |
| `HTTP_PORT` | — | Puerto del health server (default: `8003`) |
| `NODE_ENV` | — | `development` / `production` |
| `EMAIL_PROVIDER` | — | `ses` / `smtp` / `mock` |
| `SMTP_HOST` | — | Host SMTP (si `EMAIL_PROVIDER=smtp`) |
| `SMTP_PORT` | — | Puerto SMTP |
| `SMTP_USER` | — | Usuario SMTP |
| `SMTP_PASS` | — | Contraseña SMTP |
| `AWS_REGION` | — | Región AWS (si `EMAIL_PROVIDER=ses`) |
| `TWILIO_ACCOUNT_SID` | — | SID de cuenta Twilio (SMS) |
| `TWILIO_AUTH_TOKEN` | — | Token de autenticación Twilio |
| `TWILIO_FROM_NUMBER` | — | Número origen E.164 |

> En `NODE_ENV=development`, los canales email y SMS usan implementaciones mock que loggean en stdout en lugar de enviar.

---

## Desarrollo local

```bash
cd services/notification-service
npm install
npm run dev      # ts-node-dev con hot-reload
```

### Tests

```bash
npm test         # Jest
npm run lint     # ESLint
npm run build    # tsc → dist/
```

---

## Docker

```bash
docker build --target development -t nexus-notification:dev .
docker build --target production  -t nexus-notification:prod .
```

Puerto `8003` en loopback (`127.0.0.1:8003`) para el healthcheck. El proceso principal es el consumer Kafka; el HTTP server es auxiliar.

---

## Comportamiento ante fallos

| Escenario | Comportamiento |
|-----------|---------------|
| Kafka no disponible en startup | Retry con backoff exponencial (KafkaJS built-in) |
| Mensaje con JSON inválido | Log `error`, descarte, continúa |
| Envelope no cumple schema Zod | Log `error` con detalles, descarte |
| Canal de notificación falla (email/SMS) | Log `error`, mensaje se marca como procesado (no reintento infinito) |
| `SIGTERM` recibido | Drena mensajes en curso, desconecta consumer, cierra HTTP server |

---

## Seguridad aplicada

| OWASP | Control |
|-------|---------|
| A03 — Injection | Zod valida envelope y payload; sin eval ni SQL |
| A08 — Integrity Failures | Verificación opcional de `integrity_hash` SHA-256 del envelope |
| A09 — Logging | Logs estructurados Pino; sin datos sensibles (tokens, contraseñas) en logs |
