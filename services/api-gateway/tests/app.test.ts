jest.mock('../src/middleware/rateLimiter', () => ({
  createRateLimiter: () => (_req: unknown, _res: unknown, next: () => void) => next(),
  createAuthRateLimiter: () => (_req: unknown, _res: unknown, next: () => void) => next(),
}));

jest.mock('http-proxy-middleware', () => ({
  createProxyMiddleware:
    () => (_req: unknown, _res: unknown, next: () => void) =>
      next(),
}));

import request from 'supertest';
import jwt from 'jsonwebtoken';
import { app } from '../src/app';

function makeToken(scopes: string[], opts: { expired?: boolean } = {}): string {
  const privateKey = process.env['TEST_PRIVATE_KEY'] as string;
  return jwt.sign(
    { sub: 'test-user-001', scope: scopes, jti: 'test-jti' },
    privateKey,
    {
      algorithm: 'RS256',
      expiresIn: opts.expired ? -1 : '1h',
    },
  );
}

const VALID_IDEMPOTENCY_KEY = '00000000-0000-4000-8000-000000000001';

describe('GET /healthz', () => {
  it('returns 200 with service name', async () => {
    const res = await request(app).get('/healthz');
    expect(res.status).toBe(200);
    expect(res.body).toMatchObject({ status: 'ok', service: 'api-gateway' });
  });
});

describe('Unknown routes', () => {
  it('returns 404 for an unregistered path', async () => {
    const res = await request(app).get('/api/v1/does-not-exist');
    expect(res.status).toBe(404);
  });
});

describe('Authentication', () => {
  it('rejects requests with no Authorization header (401)', async () => {
    const res = await request(app).get('/api/v1/settlements');
    expect(res.status).toBe(401);
    expect(res.body).toEqual({ error: 'Unauthorized' });
  });

  it('rejects requests with malformed Bearer token (401)', async () => {
    const res = await request(app)
      .get('/api/v1/settlements')
      .set('Authorization', 'Bearer not.a.valid.jwt');
    expect(res.status).toBe(401);
  });

  it('rejects expired JWT tokens (401)', async () => {
    const token = makeToken(['settlement:read'], { expired: true });
    const res = await request(app)
      .get('/api/v1/settlements')
      .set('Authorization', `Bearer ${token}`);
    expect(res.status).toBe(401);
  });

  it('rejects "Bearer " with no token (401)', async () => {
    const res = await request(app)
      .get('/api/v1/settlements')
      .set('Authorization', 'Bearer ');
    expect(res.status).toBe(401);
  });

  it('accepts a valid RS256 JWT and forwards to the next handler', async () => {
    const token = makeToken(['settlement:read']);
    const res = await request(app)
      .get('/api/v1/settlements')
      .set('Authorization', `Bearer ${token}`);

    expect(res.status).not.toBe(401);
    expect(res.status).not.toBe(403);
  });
});

describe('Scope authorisation', () => {
  it('denies GET /settlements without settlement:read scope (403)', async () => {
    const token = makeToken(['fraud:read']);
    const res = await request(app)
      .get('/api/v1/settlements')
      .set('Authorization', `Bearer ${token}`);
    expect(res.status).toBe(403);
  });

  it('denies POST /settlements without settlement:write scope (403)', async () => {
    const token = makeToken(['settlement:read']);
    const res = await request(app)
      .post('/api/v1/settlements')
      .set('Authorization', `Bearer ${token}`)
      .set('Idempotency-Key', VALID_IDEMPOTENCY_KEY)
      .send({
        idempotency_key: VALID_IDEMPOTENCY_KEY,
        amount: 100,
        currency: 'USD',
        payer_id: '00000000-0000-4000-8000-000000000002',
        payee_id: '00000000-0000-4000-8000-000000000003',
      });
    expect(res.status).toBe(403);
  });

  it('denies fraud endpoints without fraud:read scope (403)', async () => {
    const token = makeToken(['settlement:read', 'settlement:write']);
    const res = await request(app)
      .get('/api/v1/fraud/model-info')
      .set('Authorization', `Bearer ${token}`);
    expect(res.status).toBe(403);
  });

  it('allows GET /settlements with settlement:read scope', async () => {
    const token = makeToken(['settlement:read']);
    const res = await request(app)
      .get('/api/v1/settlements')
      .set('Authorization', `Bearer ${token}`);
    expect(res.status).not.toBe(401);
    expect(res.status).not.toBe(403);
  });
});

describe('Idempotency-Key header', () => {
  const token = () => makeToken(['settlement:write']);

  it('rejects POST /settlements with no Idempotency-Key header (400)', async () => {
    const res = await request(app)
      .post('/api/v1/settlements')
      .set('Authorization', `Bearer ${token()}`)
      .send({
        idempotency_key: VALID_IDEMPOTENCY_KEY,
        amount: 100,
        currency: 'USD',
        payer_id: '00000000-0000-4000-8000-000000000002',
        payee_id: '00000000-0000-4000-8000-000000000003',
      });
    expect(res.status).toBe(400);
    expect(res.body.error).toMatch(/Idempotency-Key/);
  });

  it('rejects non-UUID Idempotency-Key header (400)', async () => {
    const res = await request(app)
      .post('/api/v1/settlements')
      .set('Authorization', `Bearer ${token()}`)
      .set('Idempotency-Key', 'not-a-uuid')
      .send({
        idempotency_key: VALID_IDEMPOTENCY_KEY,
        amount: 100,
        currency: 'USD',
        payer_id: '00000000-0000-4000-8000-000000000002',
        payee_id: '00000000-0000-4000-8000-000000000003',
      });
    expect(res.status).toBe(400);
  });
});

describe('Settlement body validation', () => {
  const token = () => makeToken(['settlement:write']);

  it('rejects negative amount (422)', async () => {
    const res = await request(app)
      .post('/api/v1/settlements')
      .set('Authorization', `Bearer ${token()}`)
      .set('Idempotency-Key', VALID_IDEMPOTENCY_KEY)
      .send({
        idempotency_key: VALID_IDEMPOTENCY_KEY,
        amount: -50,
        currency: 'USD',
        payer_id: '00000000-0000-4000-8000-000000000002',
        payee_id: '00000000-0000-4000-8000-000000000003',
      });
    expect(res.status).toBe(422);
  });

  it('rejects currency that is not 3 chars (422)', async () => {
    const res = await request(app)
      .post('/api/v1/settlements')
      .set('Authorization', `Bearer ${token()}`)
      .set('Idempotency-Key', VALID_IDEMPOTENCY_KEY)
      .send({
        idempotency_key: VALID_IDEMPOTENCY_KEY,
        amount: 100,
        currency: 'USDT',
        payer_id: '00000000-0000-4000-8000-000000000002',
        payee_id: '00000000-0000-4000-8000-000000000003',
      });
    expect(res.status).toBe(422);
  });

  it('rejects non-UUID payer_id (422)', async () => {
    const res = await request(app)
      .post('/api/v1/settlements')
      .set('Authorization', `Bearer ${token()}`)
      .set('Idempotency-Key', VALID_IDEMPOTENCY_KEY)
      .send({
        idempotency_key: VALID_IDEMPOTENCY_KEY,
        amount: 100,
        currency: 'USD',
        payer_id: 'not-a-uuid',
        payee_id: '00000000-0000-4000-8000-000000000003',
      });
    expect(res.status).toBe(422);
  });

  it('rejects amount exceeding maximum (422)', async () => {
    const res = await request(app)
      .post('/api/v1/settlements')
      .set('Authorization', `Bearer ${token()}`)
      .set('Idempotency-Key', VALID_IDEMPOTENCY_KEY)
      .send({
        idempotency_key: VALID_IDEMPOTENCY_KEY,
        amount: 99_999_999,
        currency: 'USD',
        payer_id: '00000000-0000-4000-8000-000000000002',
        payee_id: '00000000-0000-4000-8000-000000000003',
      });
    expect(res.status).toBe(422);
  });

  it('accepts a valid POST /settlements payload and proceeds (not 4xx auth error)', async () => {
    const res = await request(app)
      .post('/api/v1/settlements')
      .set('Authorization', `Bearer ${token()}`)
      .set('Idempotency-Key', VALID_IDEMPOTENCY_KEY)
      .send({
        idempotency_key: VALID_IDEMPOTENCY_KEY,
        amount: 500,
        currency: 'USD',
        payer_id: '00000000-0000-4000-8000-000000000002',
        payee_id: '00000000-0000-4000-8000-000000000003',
      });

    expect(res.status).not.toBe(401);
    expect(res.status).not.toBe(403);
    expect(res.status).not.toBe(422);
    expect(res.status).not.toBe(400);
  });
});
