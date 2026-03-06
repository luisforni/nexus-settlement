import { SESClient, SendEmailCommand, type SendEmailCommandInput } from '@aws-sdk/client-ses';
import { config } from '../config';
import { logger } from '../logger';

const sesClient = new SESClient({ region: config.AWS_REGION });

export interface EmailPayload {
  to: string;
  subject: string;
  body: string;
}

export async function sendEmail(payload: EmailPayload): Promise<void> {
  if (!config.SES_FROM_EMAIL) {
    logger.warn({ channel: 'email' }, 'SES_FROM_EMAIL not configured — skipping email');
    return;
  }

  const input: SendEmailCommandInput = {
    Destination: { ToAddresses: [payload.to] },
    Message: {
      Subject: { Data: payload.subject, Charset: 'UTF-8' },
      Body: {
        Text: { Data: payload.body, Charset: 'UTF-8' },
        Html: {
          Data: `<pre style="font-family:sans-serif">${escapeHtml(payload.body)}</pre>`,
          Charset: 'UTF-8',
        },
      },
    },
    Source: config.SES_FROM_EMAIL,
  };

  await sesClient.send(new SendEmailCommand(input));
  logger.info({ channel: 'email', subject: payload.subject }, 'Email sent');
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
