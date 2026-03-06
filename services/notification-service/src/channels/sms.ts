import twilio from 'twilio';
import { config } from '../config';
import { logger } from '../logger';

let twilioClient: ReturnType<typeof twilio> | null = null;

function getClient(): ReturnType<typeof twilio> | null {
  if (!config.TWILIO_ACCOUNT_SID || !config.TWILIO_AUTH_TOKEN) {
    return null;
  }
  if (!twilioClient) {
    twilioClient = twilio(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN);
  }
  return twilioClient;
}

export interface SmsPayload {
  to: string;
  body: string;
}

export async function sendSms(payload: SmsPayload): Promise<void> {
  const client = getClient();
  if (!client || !config.TWILIO_FROM_NUMBER) {
    logger.warn({ channel: 'sms' }, 'Twilio not configured — skipping SMS');
    return;
  }

  await client.messages.create({
    from: config.TWILIO_FROM_NUMBER,
    to: payload.to,
    body: payload.body.slice(0, 1600),
  });

  logger.info({ channel: 'sms', to: payload.to }, 'SMS sent');
}
