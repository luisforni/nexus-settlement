import pino, { Logger } from 'pino';
import pinoHttp from 'pino-http';
import { Request, Response } from 'express';
import { trace, isSpanContextValid } from '@opentelemetry/api';
import { config } from '../config';

export const logger: Logger = pino({
  level: config.logLevel,
  base: {
    service: 'api-gateway',
    environment: config.environment,
  },

  mixin() {
    const span = trace.getActiveSpan();
    const ctx = span?.spanContext();
    if (ctx && isSpanContextValid(ctx)) {
      return { trace_id: ctx.traceId, span_id: ctx.spanId };
    }
    return {};
  },

  redact: {
    paths: [
      'req.headers.authorization',
      'req.headers.cookie',
      'req.body.password',
      'req.body.token',
      'req.body.secret',
      'req.body.card_number',
      'req.body.account_number',
      '*.password',
      '*.token',
      '*.secret',
      '*.privateKey',
      '*.private_key',
    ],
    censor: '[REDACTED]',
  },
  timestamp: pino.stdTimeFunctions.isoTime,

  ...(config.environment === 'development'
    ? { transport: { target: 'pino-pretty', options: { colorize: true } } }
    : {}),
});

export const httpLogger = pinoHttp({
  logger,
  genReqId: (req: Request) =>
    (req.headers['x-request-id'] as string) ?? 'no-request-id',
  customLogLevel: (_req: Request, res: Response, err?: Error): pino.Level => {
    if (err || res.statusCode >= 500) return 'error';
    if (res.statusCode >= 400) return 'warn';
    return 'info';
  },
  customSuccessMessage: (req: Request, res: Response): string =>
    `${req.method} ${req.url} — ${res.statusCode}`,
  customErrorMessage: (req: Request, res: Response, err: Error): string =>
    `${req.method} ${req.url} — ${res.statusCode} — ${err.message}`,

  serializers: {
    req: (req) => ({
      id: req.id,
      method: req.method,
      url: req.url,
      remoteAddress: req.remoteAddress,
    }),
    res: (res) => ({
      statusCode: res.statusCode,
    }),
  },
});
