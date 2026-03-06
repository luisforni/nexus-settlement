import pino from 'pino';
import { config } from './config';

const REDACTED_PATHS = [
  'email',
  'phone',
  'phoneNumber',
  'to',
  'address',
  '*.email',
  '*.phone',
  '*.to',
  'authorization',
  'password',
  'token',
  'secret',
];

export const logger = pino({
  level: config.LOG_LEVEL,
  redact: {
    paths: REDACTED_PATHS,
    censor: '[REDACTED]',
  },
  ...(config.NODE_ENV !== 'production'
    ? {
        transport: {
          target: 'pino-pretty',
          options: { colorize: true, translateTime: 'SYS:standard' },
        },
      }
    : {}),
  base: {
    service: 'notification-service',
    env: config.NODE_ENV,
  },
});
