import http from 'http';
import { Router, Request, Response, NextFunction } from 'express';
import { createProxyMiddleware } from 'http-proxy-middleware';
import CircuitBreaker from 'opossum';
import { z } from 'zod';
import { requireScope } from '../middleware/auth';
import { config } from '../config';
import { logger } from '../middleware/logger';

const CreateSettlementSchema = z.object({
  idempotency_key: z.string().uuid('idempotency_key must be a UUID v4'),
  amount: z
    .number()
    .positive('amount must be positive')
    .max(10_000_000, 'amount exceeds maximum'),
  currency: z
    .string()
    .length(3, 'currency must be ISO 4217 (3 chars)')
    .toUpperCase(),
  payer_id: z.string().uuid('payer_id must be a UUID'),
  payee_id: z.string().uuid('payee_id must be a UUID'),
  metadata: z.record(z.string(), z.unknown()).optional(),
});

type CreateSettlementDto = z.infer<typeof CreateSettlementSchema>;

const rawSettlementProxy = createProxyMiddleware({
  target: config.upstreams.settlement,
  changeOrigin: true,

  pathRewrite: (_path: string, req: http.IncomingMessage): string => {
    return (req as Request).originalUrl ?? _path;
  },
  on: {
    proxyReq: (proxyReq: http.ClientRequest, req: http.IncomingMessage): void => {
      const expressReq = req as Request;

      if (expressReq.user?.sub) {
        proxyReq.setHeader('X-User-Id', expressReq.user.sub);
      }
      if (expressReq.body && Object.keys(expressReq.body).length > 0) {
        const bodyData = JSON.stringify(expressReq.body);
        proxyReq.setHeader('Content-Type', 'application/json');
        proxyReq.setHeader('Content-Length', Buffer.byteLength(bodyData));
        proxyReq.write(bodyData);
      }
    },
  },
});

function callSettlementService(req: Request, res: Response): Promise<void> {
  return new Promise<void>((resolve, reject) => {

    res.once('finish', resolve);

    (rawSettlementProxy as (
      req: Request,
      res: Response,
      next: (err?: unknown) => void,
    ) => void)(req, res, (err?: unknown) => {
      if (err) {
        reject(err instanceof Error ? err : new Error(String(err)));
      } else {
        resolve();
      }
    });
  });
}

const breaker = new CircuitBreaker(callSettlementService, {
  timeout: config.circuitBreaker.timeout,
  errorThresholdPercentage: config.circuitBreaker.errorThresholdPercentage,
  resetTimeout: config.circuitBreaker.resetTimeout,
  name: 'settlement-service',
});

breaker.on('open', () =>
  logger.warn({ circuit: 'settlement-service' }, 'Circuit breaker OPEN')
);
breaker.on('halfOpen', () =>
  logger.info({ circuit: 'settlement-service' }, 'Circuit breaker HALF-OPEN')
);
breaker.on('close', () =>
  logger.info({ circuit: 'settlement-service' }, 'Circuit breaker CLOSED')
);

function settlementProxy(req: Request, res: Response, _next: NextFunction): void {
  breaker.fire(req, res).catch((err: Error) => {

    if (res.headersSent) return;
    if (breaker.opened) {
      res.status(503).json({ error: 'Service Unavailable' });
    } else {
      logger.error({ err }, 'Settlement service proxy error');
      res.status(502).json({ error: 'Bad Gateway' });
    }
  });
}

function validateBody<T>(
  schema: z.ZodSchema<T>
): (req: Request, res: Response, next: NextFunction) => void {
  return (req: Request, res: Response, next: NextFunction): void => {
    const result = schema.safeParse(req.body);
    if (!result.success) {
      res.status(422).json({
        error: 'Validation Error',
        details: result.error.flatten().fieldErrors,
      });
      return;
    }
    req.body = result.data as CreateSettlementDto;
    next();
  };
}

function requireIdempotencyKey(
  req: Request,
  res: Response,
  next: NextFunction
): void {
  const key = req.headers['idempotency-key'];
  if (!key || typeof key !== 'string') {
    res.status(400).json({
      error: 'Idempotency-Key header is required for mutating requests',
    });
    return;
  }

  const uuidRegex =
    /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  if (!uuidRegex.test(key)) {
    res.status(400).json({ error: 'Idempotency-Key must be a UUID v4' });
    return;
  }
  next();
}

export const settlementRoutes = Router();

settlementRoutes.get(
  '/',
  requireScope('settlement:read'),
  settlementProxy
);

settlementRoutes.get(
  '/:id',
  requireScope('settlement:read'),
  settlementProxy
);

settlementRoutes.post(
  '/',
  requireScope('settlement:write'),
  requireIdempotencyKey,
  validateBody(CreateSettlementSchema),
  settlementProxy
);

settlementRoutes.patch(
  '/:id/cancel',
  requireScope('settlement:write'),
  requireIdempotencyKey,
  settlementProxy
);

settlementRoutes.patch(
  '/:id/reverse',
  requireScope('settlement:write'),
  requireIdempotencyKey,
  settlementProxy
);
