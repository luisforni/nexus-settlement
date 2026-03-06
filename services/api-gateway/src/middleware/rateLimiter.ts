import rateLimit, { RateLimitRequestHandler } from 'express-rate-limit';
import { RedisStore } from 'rate-limit-redis';
import { createClient } from 'redis';
import { config } from '../config';
import { logger } from './logger';

const redisClient = createClient({ url: config.redisUrl });

redisClient.on('error', (err: Error) => {

  logger.error({ err }, 'Rate-limit Redis client error');
});

void redisClient.connect().catch((err: Error) => {
  logger.warn({ err }, 'Rate-limit Redis connection failed — using memory store');
});

export function createRateLimiter(): RateLimitRequestHandler {
  return rateLimit({
    windowMs: config.rateLimit.windowMs,
    max: config.rateLimit.maxRequests,
    standardHeaders: 'draft-7',
    legacyHeaders: false,
    message: { error: 'Too Many Requests' },
    skipSuccessfulRequests: false,
    keyGenerator: (req) =>

      (req.ip ?? req.socket.remoteAddress ?? 'unknown'),
    handler: (_req, res) => {
      res.status(429).json({ error: 'Too Many Requests' });
    },

    store: new RedisStore({

      sendCommand: (...args: string[]) => (redisClient as any).sendCommand(args),
    }),
  });
}

export function createAuthRateLimiter(): RateLimitRequestHandler {
  return rateLimit({
    windowMs: 15 * 60 * 1_000,
    max: 10,
    standardHeaders: 'draft-7',
    legacyHeaders: false,
    message: { error: 'Too Many Authentication Attempts' },
    store: new RedisStore({

      sendCommand: (...args: string[]) => (redisClient as any).sendCommand(args),
      prefix: 'rl:auth:',
    }),
  });
}
