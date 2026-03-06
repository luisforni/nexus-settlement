import './tracing';
import http from 'node:http';
import { Kafka, logLevel as KafkaLogLevel } from 'kafkajs';
import { config } from './config';
import { logger } from './logger';
import { handleKafkaMessage } from './handlers/notification.handler';

const kafka = new Kafka({
  clientId: 'notification-service',
  brokers: config.KAFKA_BROKERS.split(',').map((b) => b.trim()),
  logLevel: KafkaLogLevel.WARN,
});

const consumer = kafka.consumer({ groupId: config.KAFKA_GROUP_ID });

const TOPICS = [
  config.KAFKA_TOPIC_SETTLEMENTS,
  config.KAFKA_TOPIC_FRAUD_ALERTS,
  config.KAFKA_TOPIC_NOTIFICATIONS,
  config.KAFKA_TOPIC_SETTLEMENTS_DLQ,
  config.KAFKA_TOPIC_FRAUD_DLQ,
];

async function startConsumer(): Promise<void> {
  await consumer.connect();
  logger.info({ topics: TOPICS }, 'Kafka consumer connected');

  for (const topic of TOPICS) {
    await consumer.subscribe({ topic, fromBeginning: false });
  }

  await consumer.run({
    autoCommit: true,
    autoCommitInterval: 5000,
    eachMessage: async ({ topic, message }) => {
      const value = message.value?.toString() ?? null;
      await handleKafkaMessage(topic, value);
    },
  });

  logger.info('Kafka consumer running');
}

let healthy = false;

const httpServer = http.createServer((req, res) => {
  if (req.url === '/health' || req.url === '/livez') {
    res.writeHead(healthy ? 200 : 503, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ status: healthy ? 'ok' : 'starting' }));
    return;
  }
  res.writeHead(404).end();
});

async function shutdown(signal: string): Promise<void> {
  logger.info({ signal }, 'Shutdown signal received');
  healthy = false;

  try {
    await consumer.disconnect();
    logger.info('Kafka consumer disconnected');
  } catch (err) {
    logger.error({ err }, 'Error disconnecting Kafka consumer');
  }

  httpServer.close(() => {
    logger.info('HTTP server closed');
    process.exit(0);
  });

  setTimeout(() => {
    logger.error('Forced exit after timeout');
    process.exit(1);
  }, 10_000).unref();
}

process.on('SIGTERM', () => void shutdown('SIGTERM'));
process.on('SIGINT', () => void shutdown('SIGINT'));

async function main(): Promise<void> {
  logger.info({ env: config.NODE_ENV }, 'Starting notification-service');

  if (!config.SES_FROM_EMAIL) {
    logger.warn('SES_FROM_EMAIL not configured — email notifications are disabled');
  }
  if (!config.TWILIO_ACCOUNT_SID || !config.TWILIO_AUTH_TOKEN || !config.TWILIO_FROM_NUMBER) {
    logger.warn('Twilio credentials incomplete — SMS notifications are disabled');
  }

  if (config.NODE_ENV !== 'test') {
    httpServer.listen(config.HTTP_PORT, () => {
      logger.info({ port: config.HTTP_PORT }, 'HTTP health server listening');
    });
  }

  await startConsumer();
  healthy = true;
  logger.info('Notification service ready');
}

main().catch((err) => {
  logger.error({ err }, 'Fatal startup error');
  process.exit(1);
});
