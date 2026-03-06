/**
 * k6 load test — Soak / endurance test
 *
 * Runs at moderate load for 30 minutes to expose memory leaks,
 * connection-pool exhaustion, and GC pressure.
 *
 * Usage:
 *   k6 run tests/load/soak_test.js
 */

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';
import { uuidv4 } from 'https://jslib.k6.io/k6-utils/1.4.0/index.js';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:18001';

const errorRate     = new Rate('error_rate');
const latencyTrend  = new Trend('latency_ms', true);

export const options = {
  scenarios: {
    soak: {
      executor: 'constant-arrival-rate',
      rate: 500,            // 500 RPS — moderate, sustained load
      timeUnit: '1s',
      duration: '30m',
      preAllocatedVUs: 100,
      maxVUs: 300,
    },
  },
  thresholds: {
    // Soak criteria: P99 must not degrade over time
    http_req_duration: ['p(99)<1000'],
    error_rate:        ['rate<0.02'],
  },
};

export default function () {
  const idempotencyKey = uuidv4();

  const res = http.post(
    `${BASE_URL}/api/v1/settlements`,
    JSON.stringify({
      idempotency_key: idempotencyKey,
      amount: (Math.random() * 5000 + 100).toFixed(2),
      currency: 'USD',
      payer_id: uuidv4(),
      payee_id: uuidv4(),
    }),
    {
      headers: {
        'Content-Type':    'application/json',
        'Idempotency-Key': idempotencyKey,
        'X-User-Id':       '00000000-0000-0000-0000-000000000099',
      },
    },
  );

  latencyTrend.add(res.timings.duration);
  errorRate.add(res.status >= 500 ? 1 : 0);

  check(res, { 'status 2xx': (r) => r.status >= 200 && r.status < 300 });

  sleep(0.001);
}
