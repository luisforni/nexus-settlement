/**
 * k6 load test — Fraud scoring endpoint
 *
 * Target: high-throughput scoring with P99 < 200 ms
 *
 * Usage:
 *   k6 run tests/load/fraud_score_load.js
 */

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend, Counter } from 'k6/metrics';
import { uuidv4 } from 'https://jslib.k6.io/k6-utils/1.4.0/index.js';

const BASE_URL   = __ENV.BASE_URL   || 'http://localhost:18002';
const TARGET_RPS = parseInt(__ENV.TARGET_RPS || '2000', 10);

const scoringLatency = new Trend('fraud_scoring_ms', true);
const fiveXX         = new Counter('fraud_5xx_total');
const errorRate      = new Rate('error_rate');

const CURRENCIES = ['USD', 'EUR', 'GBP', 'JPY', 'CAD', 'AUD'];

export const options = {
  scenarios: {
    fraud_scoring: {
      executor: 'ramping-arrival-rate',
      startRate: 10,
      timeUnit: '1s',
      preAllocatedVUs: 100,
      maxVUs: 500,
      stages: [
        { duration: '1m', target: TARGET_RPS },
        { duration: '3m', target: TARGET_RPS },
        { duration: '30s', target: 0 },
      ],
    },
  },
  thresholds: {
    http_req_duration: ['p(99)<200', 'p(95)<100'],
    error_rate:        ['rate<0.005'],
  },
};

export default function () {
  const amount   = (Math.random() * 50000 + 1).toFixed(2);
  const currency = CURRENCIES[Math.floor(Math.random() * CURRENCIES.length)];

  const res = http.post(
    `${BASE_URL}/api/v1/fraud/score`,
    JSON.stringify({
      settlement_id: uuidv4(),
      amount,
      currency,
      payer_id: uuidv4(),
      payee_id: uuidv4(),
    }),
    {
      headers: { 'Content-Type': 'application/json' },
      tags: { endpoint: 'fraud_score' },
    },
  );

  scoringLatency.add(res.timings.duration);

  const ok = check(res, {
    'status 200': (r) => r.status === 200,
    'has decision': (r) => {
      try {
        const b = JSON.parse(r.body);
        return ['APPROVE', 'REVIEW', 'BLOCK'].includes(b.decision);
      } catch { return false; }
    },
  });

  if (res.status >= 500) fiveXX.add(1);
  if (!ok) errorRate.add(1);

  sleep(Math.random() * 0.002);
}
