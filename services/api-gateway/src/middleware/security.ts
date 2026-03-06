import { Express, Request, Response, NextFunction } from 'express';
import helmet from 'helmet';
import cors from 'cors';
import hpp from 'hpp';
import { config } from '../config';

export function applySecurityMiddleware(app: Express): void {

  app.use(
    helmet({

      contentSecurityPolicy: {
        directives: {
          defaultSrc: ["'none'"],
          frameAncestors: ["'none'"],
        },
      },
      crossOriginEmbedderPolicy: true,
      crossOriginOpenerPolicy: { policy: 'same-origin' },
      crossOriginResourcePolicy: { policy: 'same-origin' },
      dnsPrefetchControl: { allow: false },
      frameguard: { action: 'deny' },
      hidePoweredBy: true,
      hsts: {
        maxAge: 31_536_000,
        includeSubDomains: true,
        preload: true,
      },
      ieNoOpen: true,
      noSniff: true,
      originAgentCluster: true,
      permittedCrossDomainPolicies: { permittedPolicies: 'none' },
      referrerPolicy: { policy: 'no-referrer' },
      xssFilter: true,
    })
  );

  app.use(
    cors({
      origin: (
        origin: string | undefined,
        callback: (err: Error | null, allow?: boolean) => void
      ): void => {

        if (!origin) {
          callback(null, true);
          return;
        }
        if (config.cors.allowedOrigins.includes(origin)) {
          callback(null, true);
        } else {
          callback(new Error(`CORS: origin not allowed — ${origin}`));
        }
      },
      credentials: true,
      methods: ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'],
      allowedHeaders: [
        'Content-Type',
        'Authorization',
        'X-Request-Id',
        'Idempotency-Key',
      ],
      exposedHeaders: ['X-Request-Id', 'Retry-After'],
      maxAge: 86_400,
    })
  );

  app.use(hpp());

  app.disable('etag');

  app.disable('x-powered-by');

  if (config.environment !== 'development') {
    app.set('trust proxy', 1);
  }

  app.use((_req: Request, res: Response, next: NextFunction): void => {
    res.removeHeader('Server');
    next();
  });
}
