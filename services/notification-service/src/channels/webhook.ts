import axios, { AxiosError } from 'axios';
import { config } from '../config';
import { logger } from '../logger';

const PRIVATE_HOST_RE =
  /^(localhost|127\.|10\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.|::1|fd[0-9a-f]{2}:)/i;

export interface WebhookPayload {
  url: string;
  event: string;
  data: Record<string, unknown>;
}

function validateUrl(raw: string): URL {
  let parsed: URL;
  try {
    parsed = new URL(raw);
  } catch {
    throw new Error(`Invalid webhook URL: ${raw}`);
  }

  if (parsed.protocol !== 'https:') {
    throw new Error('Webhook URL must use HTTPS (OWASP A10 SSRF)');
  }

  if (PRIVATE_HOST_RE.test(parsed.hostname)) {
    throw new Error(`Webhook URL targets a private/loopback host: ${parsed.hostname}`);
  }

  return parsed;
}

export async function sendWebhook(payload: WebhookPayload): Promise<void> {
  validateUrl(payload.url);

  const body = {
    event: payload.event,
    timestamp: new Date().toISOString(),
    data: payload.data,
  };

  let attempt = 0;
  const maxAttempts = config.WEBHOOK_MAX_RETRIES + 1;

  while (attempt < maxAttempts) {
    try {
      await axios.post(payload.url, body, {
        timeout: config.WEBHOOK_TIMEOUT_MS,
        headers: { 'Content-Type': 'application/json', 'X-Nexus-Event': payload.event },
      });
      logger.info(
        { channel: 'webhook', event: payload.event, attempt: attempt + 1 },
        'Webhook delivered',
      );
      return;
    } catch (err) {
      const status = err instanceof AxiosError ? err.response?.status : undefined;
      const delay = 2 ** attempt * 500;
      logger.warn(
        { channel: 'webhook', event: payload.event, attempt: attempt + 1, status, delay },
        'Webhook attempt failed — will retry',
      );
      attempt += 1;
      if (attempt < maxAttempts) {
        await new Promise((r) => setTimeout(r, delay));
      }
    }
  }

  logger.error(
    { channel: 'webhook', event: payload.event, maxAttempts },
    'Webhook delivery failed after all retries',
  );
}
