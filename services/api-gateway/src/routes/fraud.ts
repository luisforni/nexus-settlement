import http from 'http';
import { Router, Request, Response, NextFunction } from 'express';
import { createProxyMiddleware } from 'http-proxy-middleware';
import CircuitBreaker from 'opossum';
import { requireScope } from '../middleware/auth';
import { config } from '../config';
import { logger } from '../middleware/logger';

const rawFraudProxy = createProxyMiddleware({
  target: config.upstreams.fraud,
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
        const bodyStr = JSON.stringify(expressReq.body);
        proxyReq.setHeader('Content-Type', 'application/json');
        proxyReq.setHeader('Content-Length', Buffer.byteLength(bodyStr));
        proxyReq.write(bodyStr);
      }
    },
  },
});

function callFraudService(req: Request, res: Response): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    res.once('finish', resolve);

    (rawFraudProxy as (
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

const breaker = new CircuitBreaker(callFraudService, {
  timeout: config.circuitBreaker.timeout,
  errorThresholdPercentage: config.circuitBreaker.errorThresholdPercentage,
  resetTimeout: config.circuitBreaker.resetTimeout,
  name: 'fraud-detection-service',
});

breaker.on('open', () =>
  logger.warn({ circuit: 'fraud-detection-service' }, 'Circuit breaker OPEN'),
);
breaker.on('halfOpen', () =>
  logger.info({ circuit: 'fraud-detection-service' }, 'Circuit breaker HALF-OPEN'),
);
breaker.on('close', () =>
  logger.info({ circuit: 'fraud-detection-service' }, 'Circuit breaker CLOSED'),
);

function fraudProxy(req: Request, res: Response, _next: NextFunction): void {
  breaker.fire(req, res).catch((err: Error) => {
    if (res.headersSent) return;
    if (breaker.opened) {
      res.status(503).json({ error: 'Service Unavailable' });
    } else {
      logger.error({ err }, 'Fraud detection service proxy error');
      res.status(502).json({ error: 'Bad Gateway' });
    }
  });
}

export const fraudRoutes = Router();

fraudRoutes.post('/score', requireScope('fraud:read'), fraudProxy);

fraudRoutes.get('/explain/:settlement_id', requireScope('fraud:read'), fraudProxy);

fraudRoutes.get('/model-info', requireScope('fraud:read'), fraudProxy);
