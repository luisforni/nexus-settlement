import 'dotenv/config';
import express, { Express, Request, Response, NextFunction } from 'express';
import { v4 as uuidv4 } from 'uuid';

import { config } from './config';
import { applySecurityMiddleware } from './middleware/security';
import { httpLogger } from './middleware/logger';
import { createRateLimiter } from './middleware/rateLimiter';
import { authenticate } from './middleware/auth';
import { settlementRoutes } from './routes/settlements';
import { fraudRoutes } from './routes/fraud';
import { healthRoutes } from './routes/health';
import { logger } from './middleware/logger';

const app: Express = express();

app.use((req: Request, _res: Response, next: NextFunction): void => {
  req.headers['x-request-id'] =
    (req.headers['x-request-id'] as string) || uuidv4();
  next();
});

applySecurityMiddleware(app);

app.use(httpLogger);

app.use('/api/', createRateLimiter());

app.use(
  express.json({
    limit: '64kb',
    strict: true,
  })
);
app.use(express.urlencoded({ extended: false, limit: '16kb' }));

app.use('/healthz', healthRoutes);

app.use('/api/v1/settlements', authenticate, settlementRoutes);
app.use('/api/v1/fraud', authenticate, fraudRoutes);

app.use((_req: Request, res: Response): void => {
  res.status(404).json({ error: 'Not Found' });
});

app.use((err: any, _req: Request, res: Response, _next: NextFunction): void => {
  const status: number = err.status ?? err.statusCode ?? 500;
  const message: string =
    status < 500
      ? (err.message as string)
      : 'Internal Server Error';

  if (status >= 500) {
    logger.error({ err }, 'Unhandled error');
  }

  res.status(status).json({ error: message });
});

if (process.env.NODE_ENV !== 'test') {
  const server = app.listen(config.port, () => {
    logger.info(
      { port: config.port, environment: config.environment },
      'API Gateway started'
    );
  });

  const shutdown = (signal: string): void => {
    logger.info({ signal }, 'Shutdown signal received');
    server.close(() => {
      logger.info('HTTP server closed. Exiting.');
      process.exit(0);
    });

    setTimeout(() => {
      logger.error('Forced shutdown after timeout');
      process.exit(1);
    }, 10_000).unref();
  };

  process.on('SIGTERM', () => shutdown('SIGTERM'));
  process.on('SIGINT', () => shutdown('SIGINT'));
}

export { app };
