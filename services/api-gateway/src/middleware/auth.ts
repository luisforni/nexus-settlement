import { Request, Response, NextFunction } from 'express';
import jwt from 'jsonwebtoken';
import { config } from '../config';
import { logger } from './logger';

export interface JwtPayload {
  sub: string;
  scope: string[];
  iat: number;
  exp: number;
  jti: string;
}

declare global {
  namespace Express {
    interface Request {
      user?: JwtPayload;
    }
  }
}

function getPublicKey(): string {
  const pem = Buffer.from(config.jwt.publicKeyBase64, 'base64').toString('utf8');
  return pem;
}

const PUBLIC_KEY = getPublicKey();

export function authenticate(
  req: Request,
  res: Response,
  next: NextFunction
): void {
  const authHeader = req.headers.authorization;

  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    res.status(401).json({ error: 'Unauthorized' });
    return;
  }

  const token = authHeader.slice(7);

  try {
    const payload = jwt.verify(token, PUBLIC_KEY, {
      algorithms: [config.jwt.algorithm],
      ...(config.jwt.issuer ? { issuer: config.jwt.issuer } : {}),
      ...(config.jwt.audience ? { audience: config.jwt.audience } : {}),
      complete: false,
    }) as JwtPayload;

    req.user = payload;
    next();
  } catch (err) {

    logger.warn(
      {
        requestId: req.headers['x-request-id'],
        error: (err as Error).message,
        path: req.path,
      },
      'JWT validation failed'
    );
    res.status(401).json({ error: 'Unauthorized' });
  }
}

export function requireScope(
  ...requiredScopes: string[]
): (req: Request, res: Response, next: NextFunction) => void {
  return (req: Request, res: Response, next: NextFunction): void => {
    const userScopes = req.user?.scope ?? [];
    const hasAll = requiredScopes.every((s) => userScopes.includes(s));

    if (!hasAll) {
      logger.warn(
        {
          requestId: req.headers['x-request-id'],
          userId: req.user?.sub,
          required: requiredScopes,
          actual: userScopes,
        },
        'Insufficient scope — access denied'
      );
      res.status(403).json({ error: 'Forbidden' });
      return;
    }

    next();
  };
}
