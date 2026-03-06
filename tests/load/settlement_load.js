/**
 * k6 load test — Settlement creation (happy path)
 *
 * Target: 5 000 RPS sustained for 2 minutes with P99 < 500 ms
 *
 * Usage:
 *   k6 run tests/load/settlement_load.js
 *
 * Override defaults via environment variables:
 *   k6 run -e BASE_URL=http://localhost:4000 \
 *           -e TOKEN=<jwt> \
 *           -e TARGET_RPS=5000 \
 *           tests/load/settlement_load.js
 */

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend, Counter } from 'k6/metrics';
import { uuidv4 } from 'https://jslib.k6.io/k6-utils/1.4.0/index.js';

// ── Configuration ──────────────────────────────────────────────────────────────
const BASE_URL   = __ENV.BASE_URL   || 'http://localhost:18001';
const TOKEN      = __ENV.TOKEN      || '';
const TARGET_RPS = parseInt(__ENV.TARGET_RPS || '5000', 10);

// ── Custom metrics ─────────────────────────────────────────────────────────────
const settlementCreated = new Counter('settlement_created_total');
const settlementFailed  = new Counter('settlement_failed_total');
const fraudBlocked      = new Counter('settlement_fraud_blocked_total');
const p99Latency        = new Trend('settlement_p99_ms', true);
const errorRate         = new Rate('error_rate');

// ── Load profile ───────────────────────────────────────────────────────────────
// Ramp up over 2 min, sustain at TARGET_RPS for 2 min, ramp down 1 min.
export const options = {
  scenarios: {
    settlement_creation: {
      executor: 'ramping-arrival-rate',
      startRate: 10,
      timeUnit: '1s',
      preAllocatedVUs: 200,
      maxVUs: 1000,
      stages: [
        { duration: '2m', target: TARGET_RPS },  // ramp-up
        { duration: '2m', target: TARGET_RPS },  // sustain
        { duration: '1m', target: 0 },           // ramp-down
      ],
    },
  },
  thresholds: {
    // P99 response time must stay under 500 ms
    http_req_duration:      ['p(99)<500'],
    // Error rate must stay below 1%
    error_rate:             ['rate<0.01'],
    // At least 99% of requests must succeed (2xx or expected 4xx)
    http_req_failed:        ['rate<0.01'],
  },
};

// ── VU code ───────────────────────────────────────────────────────────────────
export default function () {
  const idempotencyKey = uuidv4();
  const payerId        = uuidv4();
  const payeeId        = uuidv4();
  const amount         = (Math.random() * 9900 + 100).toFixed(2);

  const payload = JSON.stringify({
    idempotency_key: idempotencyKey,
    amount,
    currency: 'USD',
    payer_id:  payerId,
    payee_id:  payeeId,
  });

  const headers = {
    'Content-Type':    'application/json',
    'Idempotency-Key': idempotencyKey,
    'X-User-Id':       '00000000-0000-0000-0000-000000000099',
  };

  if (TOKEN) {
    headers['Authorization'] = `Bearer ${TOKEN}`;
  }

  const res = http.post(`${BASE_URL}/api/v1/settlements`, payload, {
    headers,
    tags: { endpoint: 'create_settlement' },
  });

  p99Latency.add(res.timings.duration);

  const ok = check(res, {
    'status 201': (r) => r.status === 201,
    'has settlement id': (r) => {
      try { return !!JSON.parse(r.body).id; }
      catch { return false; }
    },
  });

  if (res.status === 201) {
    settlementCreated.add(1);
  } else if (res.status === 403) {
    fraudBlocked.add(1);
  } else {
    settlementFailed.add(1);
    errorRate.add(1);
  }

  if (!ok) errorRate.add(1);

  // 1–3 ms think time to model realistic client behaviour
  sleep(Math.random() * 0.003);
}
