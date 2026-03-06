import { Router, Request, Response } from 'express';
import { createClient } from 'redis';
import { config } from '../config';
import { logger } from '../middleware/logger';

export const healthRoutes = Router();

const startTime = Date.now();

healthRoutes.get('/', (_req: Request, res: Response): void => {
  res.status(200).json({
    status: 'ok',
    service: 'api-gateway',
    uptime_seconds: Math.floor((Date.now() - startTime) / 1_000),
    timestamp: new Date().toISOString(),
  });
});

healthRoutes.get('/ready', async (_req: Request, res: Response): Promise<void> => {
  const checks: Record<string, 'ok' | 'error'> = {};

  try {
    const client = createClient({ url: config.redisUrl });
    await client.connect();
    await client.ping();
    await client.disconnect();
    checks['redis'] = 'ok';
  } catch (err) {
    logger.warn({ err }, 'Redis health check failed');
    checks['redis'] = 'error';
  }

  const healthy = Object.values(checks).every((v) => v === 'ok');

  res.status(healthy ? 200 : 503).json({
    status: healthy ? 'ready' : 'not_ready',
    checks,
    timestamp: new Date().toISOString(),
  });
});
