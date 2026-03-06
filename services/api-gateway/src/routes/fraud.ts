import { Router, Request, Response } from 'express';
import http from 'http';
import { createProxyMiddleware } from 'http-proxy-middleware';
import { requireScope } from '../middleware/auth';
import { config } from '../config';
import { logger } from '../middleware/logger';

const fraudProxy = createProxyMiddleware({
  target: config.upstreams.fraud,
  changeOrigin: true,

  pathRewrite: (_path: string, req: http.IncomingMessage): string => {
    return (req as Request).originalUrl ?? _path;
  },
  on: {
    proxyReq: (proxyReq, req) => {

      if ((req as Request).body) {
        const bodyStr = JSON.stringify((req as Request).body);
        proxyReq.setHeader('Content-Type', 'application/json');
        proxyReq.setHeader('Content-Length', Buffer.byteLength(bodyStr));
        proxyReq.write(bodyStr);
      }
    },
    error: (err: Error, _req: Request, res: Response) => {
      logger.error({ err }, 'Fraud detection service proxy error');
      (res as Response).status(502).json({ error: 'Bad Gateway' });
    },
  },
});

export const fraudRoutes = Router();

fraudRoutes.post('/score', requireScope('fraud:read'), fraudProxy);

fraudRoutes.get('/explain/:settlement_id', requireScope('fraud:read'), fraudProxy);

fraudRoutes.get('/model-info', requireScope('fraud:read'), fraudProxy);
