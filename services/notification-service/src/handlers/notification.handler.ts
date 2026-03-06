import { z } from 'zod';
import { logger } from '../logger';
import { sendEmail } from '../channels/email';
import { sendSms } from '../channels/sms';
import { sendWebhook } from '../channels/webhook';

const KafkaEnvelopeSchema = z.object({
  event_id: z.string().uuid(),
  event_type: z.string().min(1),
  timestamp: z.string().datetime(),
  payload: z.record(z.unknown()),
  integrity_hash: z.string().optional(),
});

export type KafkaEnvelope = z.infer<typeof KafkaEnvelopeSchema>;

interface SettlementCompletedPayload {
  settlement_id: string;
  amount: number;
  currency: string;
  user_email?: string;
  user_phone?: string;
  webhook_url?: string;
}

interface FraudAlertPayload {
  transaction_id: string;
  risk_score: number;
  decision: 'REVIEW' | 'BLOCK';
  user_email?: string;
  webhook_url?: string;
}

interface GenericNotificationPayload {
  channel: 'email' | 'sms' | 'webhook';
  to: string;
  subject?: string;
  message: string;
  event?: string;
  data?: Record<string, unknown>;
}

export async function handleKafkaMessage(
  topic: string,
  rawValue: string | null,
): Promise<void> {
  if (!rawValue) {
    logger.warn({ topic }, 'Received empty Kafka message — skipping');
    return;
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(rawValue);
  } catch {
    logger.error({ topic }, 'Kafka message is not valid JSON — discarding');
    return;
  }

  const envelope = KafkaEnvelopeSchema.safeParse(parsed);
  if (!envelope.success) {
    logger.error(
      { topic, issues: envelope.error.issues },
      'Kafka envelope schema validation failed — discarding',
    );
    return;
  }

  const { event_type, payload, event_id } = envelope.data;
  logger.info({ topic, event_type, event_id }, 'Processing notification event');

  try {
    switch (event_type) {
      case 'settlement.completed':
        await handleSettlementCompleted(payload as SettlementCompletedPayload);
        break;

      case 'settlement.failed':
        await handleSettlementFailed(payload as SettlementCompletedPayload);
        break;

      case 'fraud.review':
      case 'fraud.blocked':
        await handleFraudAlert(payload as FraudAlertPayload);
        break;

      case 'notification.send':
        await handleGenericNotification(payload as GenericNotificationPayload);
        break;

      default:
        logger.debug({ topic, event_type }, 'Unhandled event type — no notification sent');
    }
  } catch (err) {
    logger.error({ topic, event_type, event_id, err }, 'Failed to dispatch notification');

  }
}

async function handleSettlementCompleted(p: SettlementCompletedPayload): Promise<void> {
  const subject = `Settlement ${p.settlement_id} completed`;
  const body =
    `Your settlement (${p.settlement_id}) for ` +
    `${p.amount} ${p.currency} has been completed successfully.`;

  const tasks: Array<Promise<void>> = [];

  if (p.user_email) {
    tasks.push(sendEmail({ to: p.user_email, subject, body }));
  }
  if (p.user_phone) {
    tasks.push(sendSms({ to: p.user_phone, body: `${subject}. ${body}` }));
  }
  if (p.webhook_url) {
    tasks.push(
      sendWebhook({ url: p.webhook_url, event: 'settlement.completed', data: { ...p } }),
    );
  }

  await Promise.allSettled(tasks);
}

async function handleSettlementFailed(p: SettlementCompletedPayload): Promise<void> {
  const subject = `Settlement ${p.settlement_id} failed`;
  const body =
    `Your settlement (${p.settlement_id}) for ` +
    `${p.amount} ${p.currency} could not be completed. Please contact support.`;

  const tasks: Array<Promise<void>> = [];

  if (p.user_email) {
    tasks.push(sendEmail({ to: p.user_email, subject, body }));
  }
  if (p.webhook_url) {
    tasks.push(
      sendWebhook({ url: p.webhook_url, event: 'settlement.failed', data: { ...p } }),
    );
  }

  await Promise.allSettled(tasks);
}

async function handleFraudAlert(p: FraudAlertPayload): Promise<void> {
  const action = p.decision === 'BLOCK' ? 'blocked' : 'flagged for review';
  const subject = `Security alert — transaction ${p.transaction_id} ${action}`;
  const body =
    `Transaction ${p.transaction_id} was ${action} by our fraud detection system ` +
    `(risk score: ${(p.risk_score * 100).toFixed(1)}%). ` +
    `If this was not you, please contact support immediately.`;

  const tasks: Array<Promise<void>> = [];

  if (p.user_email) {
    tasks.push(sendEmail({ to: p.user_email, subject, body }));
  }
  if (p.webhook_url) {
    tasks.push(
      sendWebhook({
        url: p.webhook_url,
        event: `fraud.${p.decision.toLowerCase()}`,
        data: { ...p },
      }),
    );
  }

  await Promise.allSettled(tasks);
}

async function handleGenericNotification(p: GenericNotificationPayload): Promise<void> {
  switch (p.channel) {
    case 'email':
      await sendEmail({ to: p.to, subject: p.subject ?? 'Notification', body: p.message });
      break;
    case 'sms':
      await sendSms({ to: p.to, body: p.message });
      break;
    case 'webhook':
      await sendWebhook({
        url: p.to,
        event: p.event ?? 'notification',
        data: p.data ?? { message: p.message },
      });
      break;
  }
}
