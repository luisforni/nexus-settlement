import { config as loadDotenv } from 'dotenv';
import { z } from 'zod';

loadDotenv();

const schema = z.object({

  NODE_ENV: z.enum(['development', 'production', 'test']).default('production'),
  LOG_LEVEL: z.enum(['fatal', 'error', 'warn', 'info', 'debug', 'trace']).default('info'),
  HTTP_PORT: z.coerce.number().int().min(1024).max(65535).default(8003),

  KAFKA_BROKERS: z.string().min(1),
  KAFKA_GROUP_ID: z.string().default('notification-service'),
  KAFKA_TOPIC_SETTLEMENTS: z.string().default('nexus.settlements'),
  KAFKA_TOPIC_FRAUD_ALERTS: z.string().default('nexus.fraud.alerts'),
  KAFKA_TOPIC_NOTIFICATIONS: z.string().default('nexus.notifications'),
  KAFKA_TOPIC_SETTLEMENTS_DLQ: z.string().default('nexus.settlements.dlq'),
  KAFKA_TOPIC_FRAUD_DLQ: z.string().default('nexus.fraud.dlq'),

  AWS_REGION: z.string().default('us-east-1'),
  AWS_ACCESS_KEY_ID: z.string().optional(),
  AWS_SECRET_ACCESS_KEY: z.string().optional(),
  SES_FROM_EMAIL: z.string().email().optional(),

  TWILIO_ACCOUNT_SID: z.string().optional(),
  TWILIO_AUTH_TOKEN: z.string().optional(),
  TWILIO_FROM_NUMBER: z.string().optional(),

  WEBHOOK_TIMEOUT_MS: z.coerce.number().int().min(1000).default(5000),
  WEBHOOK_MAX_RETRIES: z.coerce.number().int().min(0).max(10).default(3),
});

function load() {
  const result = schema.safeParse(process.env);
  if (!result.success) {
    const issues = result.error.issues
      .map((i) => `  [${i.path.join('.')}] ${i.message}`)
      .join('\nnnnnn');
    throw new Error(`Configuration validation failed:\n${issues}`);
  }
  return result.data;
}

export const config = load();
export type Config = typeof config;
