import crypto from 'crypto';
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
  amount: string;
  currency: string;
  user_email?: string;
  user_phone?: string;
  webhook_url?: string;
  reason?: string;
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

interface DlqPermanentlyFailedPayload {
  settlement_id?: string;
  original_topic: string;
  error_type: string;
  error_message: string;
  retry_count: number;
  dlq_topic: string;
  ops_webhook_url?: string;
  ops_email?: string;
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

  const { event_type, payload, event_id, integrity_hash } = envelope.data;

  if (integrity_hash) {
    const canonical = JSON.stringify(
      payload,
      Object.keys(payload).sort() as (keyof typeof payload)[],
    );
    const computed = crypto.createHash('sha256').update(canonical).digest('hex');
    if (computed !== integrity_hash) {
      logger.error(
        { topic, event_type, event_id },
        'Integrity hash mismatch — discarding tampered event',
      );
      return;
    }
  }

  logger.info({ topic, event_type, event_id }, 'Processing notification event');

  try {
    switch (event_type) {
      case 'settlement.completed':
        await handleSettlementCompleted(payload as unknown as SettlementCompletedPayload);
        break;

      case 'settlement.cancelled':
        await handleSettlementCancelled(payload as unknown as SettlementCompletedPayload);
        break;

      case 'settlement.reversed':
        await handleSettlementReversed(payload as unknown as SettlementCompletedPayload);
        break;

      case 'settlement.failed':
        await handleSettlementFailed(payload as unknown as SettlementCompletedPayload);
        break;

      case 'fraud.review':
      case 'fraud.blocked':
        await handleFraudAlert(payload as unknown as FraudAlertPayload);
        break;

      case 'notification.send':
        await handleGenericNotification(payload as unknown as GenericNotificationPayload);
        break;

      case 'dlq.permanently_failed':
        await handleDlqPermanentlyFailed(payload as unknown as DlqPermanentlyFailedPayload);
        break;

      default:
        logger.debug({ topic, event_type }, 'Unhandled event type — no notification sent');
    }
  } catch (err) {
    const errorDetail = err instanceof Error
      ? { message: err.message, stack: err.stack }
      : err;
    logger.error({ topic, event_type, event_id, error: errorDetail }, 'Failed to dispatch notification');
  }
}

function dispatchWebhook(payload: Parameters<typeof sendWebhook>[0], eventLabel: string): void {
  void sendWebhook(payload).catch((err) =>
    logger.error(
      { err, event: eventLabel },
      'Background webhook delivery failed',
    ),
  );
}

function logSettled(results: PromiseSettledResult<void>[], eventLabel: string): void {
  for (const result of results) {
    if (result.status === 'rejected') {
      logger.error(
        { error: result.reason, event: eventLabel },
        'Channel delivery failed',
      );
    }
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

  logSettled(await Promise.allSettled(tasks), 'settlement.completed');

  if (p.webhook_url) {
    dispatchWebhook({ url: p.webhook_url, event: 'settlement.completed', data: { ...p } }, 'settlement.completed');
  }
}

async function handleSettlementCancelled(p: SettlementCompletedPayload): Promise<void> {
  const subject = `Settlement ${p.settlement_id} cancelled`;
  const body =
    `Your settlement (${p.settlement_id}) for ` +
    `${p.amount} ${p.currency} has been cancelled.`;

  const tasks: Array<Promise<void>> = [];

  if (p.user_email) {
    tasks.push(sendEmail({ to: p.user_email, subject, body }));
  }
  if (p.user_phone) {
    tasks.push(sendSms({ to: p.user_phone, body: `${subject}. ${body}` }));
  }

  logSettled(await Promise.allSettled(tasks), 'settlement.cancelled');

  if (p.webhook_url) {
    dispatchWebhook({ url: p.webhook_url, event: 'settlement.cancelled', data: { ...p } }, 'settlement.cancelled');
  }
}

async function handleSettlementReversed(p: SettlementCompletedPayload): Promise<void> {
  const subject = `Settlement ${p.settlement_id} reversed`;
  const body =
    `Your settlement (${p.settlement_id}) for ` +
    `${p.amount} ${p.currency} has been reversed.`;

  const tasks: Array<Promise<void>> = [];

  if (p.user_email) {
    tasks.push(sendEmail({ to: p.user_email, subject, body }));
  }
  if (p.user_phone) {
    tasks.push(sendSms({ to: p.user_phone, body: `${subject}. ${body}` }));
  }

  logSettled(await Promise.allSettled(tasks), 'settlement.reversed');

  if (p.webhook_url) {
    dispatchWebhook({ url: p.webhook_url, event: 'settlement.reversed', data: { ...p } }, 'settlement.reversed');
  }
}

async function handleSettlementFailed(p: SettlementCompletedPayload): Promise<void> {
  const subject = `Settlement ${p.settlement_id} failed`;
  const body =
    `Your settlement (${p.settlement_id}) for ` +
    `${p.amount} ${p.currency} could not be completed.` +
    (p.reason ? ` Reason: ${p.reason}.` : '') +
    ' Please contact support.';

  const tasks: Array<Promise<void>> = [];

  if (p.user_email) {
    tasks.push(sendEmail({ to: p.user_email, subject, body }));
  }
  if (p.user_phone) {
    tasks.push(sendSms({ to: p.user_phone, body: `${subject}. ${body}` }));
  }

  logSettled(await Promise.allSettled(tasks), 'settlement.failed');

  if (p.webhook_url) {
    dispatchWebhook({ url: p.webhook_url, event: 'settlement.failed', data: { ...p } }, 'settlement.failed');
  }
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

  logSettled(await Promise.allSettled(tasks), `fraud.${p.decision.toLowerCase()}`);

  if (p.webhook_url) {
    dispatchWebhook(
      { url: p.webhook_url, event: `fraud.${p.decision.toLowerCase()}`, data: { ...p } },
      `fraud.${p.decision.toLowerCase()}`,
    );
  }
}

async function handleDlqPermanentlyFailed(p: DlqPermanentlyFailedPayload): Promise<void> {
  const subject = `[OPS ALERT] Permanently failed message on ${p.dlq_topic}`;
  const body = [
    `A message has exhausted all retry attempts and been permanently failed.`,
    ``,
    `Topic:        ${p.original_topic}`,
    `DLQ Topic:    ${p.dlq_topic}`,
    p.settlement_id ? `Settlement ID: ${p.settlement_id}` : null,
    `Retry count:  ${p.retry_count}`,
    `Error type:   ${p.error_type}`,
    `Error:        ${p.error_message}`,
    ``,
    `Manual intervention required.`,
  ]
    .filter((line) => line !== null)
    .join('\nn');

  const tasks: Array<Promise<void>> = [];

  if (p.ops_email) {
    tasks.push(sendEmail({ to: p.ops_email, subject, body }));
  }

  logSettled(await Promise.allSettled(tasks), 'dlq.permanently_failed');

  if (p.ops_webhook_url) {
    dispatchWebhook(
      {
        url: p.ops_webhook_url,
        event: 'dlq.permanently_failed',
        data: { ...p },
      },
      'dlq.permanently_failed',
    );
  }
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
      dispatchWebhook(
        { url: p.to, event: p.event ?? 'notification', data: p.data ?? { message: p.message } },
        p.event ?? 'notification',
      );
      break;
  }
}
