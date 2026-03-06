import { handleKafkaMessage } from '../src/handlers/notification.handler';

jest.mock('../src/channels/email', () => ({
  sendEmail: jest.fn().mockResolvedValue(undefined),
}));
jest.mock('../src/channels/sms', () => ({
  sendSms: jest.fn().mockResolvedValue(undefined),
}));
jest.mock('../src/channels/webhook', () => ({
  sendWebhook: jest.fn().mockResolvedValue(undefined),
}));

import { sendEmail } from '../src/channels/email';
import { sendSms } from '../src/channels/sms';
import { sendWebhook } from '../src/channels/webhook';

const mockSendEmail = sendEmail as jest.MockedFunction<typeof sendEmail>;
const mockSendSms = sendSms as jest.MockedFunction<typeof sendSms>;
const mockSendWebhook = sendWebhook as jest.MockedFunction<typeof sendWebhook>;

function envelope(event_type: string, payload: Record<string, unknown>): string {
  return JSON.stringify({
    event_id: 'a1b2c3d4-e5f6-7890-abcd-ef1234567890',
    event_type,
    timestamp: new Date().toISOString(),
    payload,
  });
}

beforeEach(() => {
  jest.clearAllMocks();
});

describe('handleKafkaMessage', () => {
  it('discards null messages without throwing', async () => {
    await expect(handleKafkaMessage('nexus.settlements', null)).resolves.toBeUndefined();
    expect(mockSendEmail).not.toHaveBeenCalled();
  });

  it('discards invalid JSON without throwing', async () => {
    await expect(handleKafkaMessage('nexus.settlements', '{bad json')).resolves.toBeUndefined();
    expect(mockSendEmail).not.toHaveBeenCalled();
  });

  it('discards envelope with missing required fields', async () => {
    const bad = JSON.stringify({ event_type: 'settlement.completed' });
    await expect(handleKafkaMessage('nexus.settlements', bad)).resolves.toBeUndefined();
    expect(mockSendEmail).not.toHaveBeenCalled();
  });

  it('sends email and SMS on settlement.completed with both contact methods', async () => {
    const msg = envelope('settlement.completed', {
      settlement_id: 'stl_001',
      amount: 1000,
      currency: 'USD',
      user_email: 'user@example.com',
      user_phone: '+15551234567',
    });
    await handleKafkaMessage('nexus.settlements', msg);

    expect(mockSendEmail).toHaveBeenCalledTimes(1);
    expect(mockSendEmail.mock.calls[0]?.[0]).toMatchObject({
      to: 'user@example.com',
      subject: expect.stringContaining('stl_001'),
    });
    expect(mockSendSms).toHaveBeenCalledTimes(1);
    expect(mockSendSms.mock.calls[0]?.[0]).toMatchObject({ to: '+15551234567' });
    expect(mockSendWebhook).not.toHaveBeenCalled();
  });

  it('sends webhook on settlement.completed when webhook_url provided', async () => {
    const msg = envelope('settlement.completed', {
      settlement_id: 'stl_002',
      amount: 500,
      currency: 'EUR',
      webhook_url: 'https://partner.example.com/hooks',
    });
    await handleKafkaMessage('nexus.settlements', msg);

    expect(mockSendWebhook).toHaveBeenCalledTimes(1);
    expect(mockSendWebhook.mock.calls[0]?.[0]).toMatchObject({
      url: 'https://partner.example.com/hooks',
      event: 'settlement.completed',
    });
    expect(mockSendEmail).not.toHaveBeenCalled();
  });

  it('sends email on settlement.failed', async () => {
    const msg = envelope('settlement.failed', {
      settlement_id: 'stl_003',
      amount: 750,
      currency: 'GBP',
      user_email: 'user@example.com',
    });
    await handleKafkaMessage('nexus.settlements', msg);
    expect(mockSendEmail).toHaveBeenCalledTimes(1);
    expect(mockSendEmail.mock.calls[0]?.[0]?.subject).toContain('failed');
  });

  it('sends email on fraud.blocked event', async () => {
    const msg = envelope('fraud.blocked', {
      transaction_id: 'txn_999',
      risk_score: 0.92,
      decision: 'BLOCK',
      user_email: 'user@example.com',
    });
    await handleKafkaMessage('nexus.fraud.alerts', msg);
    expect(mockSendEmail).toHaveBeenCalledTimes(1);
    expect(mockSendEmail.mock.calls[0]?.[0]?.subject).toContain('blocked');
  });

  it('handles notification.send for email channel', async () => {
    const msg = envelope('notification.send', {
      channel: 'email',
      to: 'ops@example.com',
      subject: 'System alert',
      message: 'Something happened.',
    });
    await handleKafkaMessage('nexus.notifications', msg);
    expect(mockSendEmail).toHaveBeenCalledWith({
      to: 'ops@example.com',
      subject: 'System alert',
      body: 'Something happened.',
    });
  });

  it('handles notification.send for sms channel', async () => {
    const msg = envelope('notification.send', {
      channel: 'sms',
      to: '+15559999999',
      message: 'Your OTP is 123456.',
    });
    await handleKafkaMessage('nexus.notifications', msg);
    expect(mockSendSms).toHaveBeenCalledWith({
      to: '+15559999999',
      body: 'Your OTP is 123456.',
    });
  });

  it('silently ignores unhandled event types', async () => {
    const msg = envelope('some.unknown.event', { foo: 'bar' });
    await expect(handleKafkaMessage('nexus.notifications', msg)).resolves.toBeUndefined();
    expect(mockSendEmail).not.toHaveBeenCalled();
    expect(mockSendSms).not.toHaveBeenCalled();
    expect(mockSendWebhook).not.toHaveBeenCalled();
  });
});

describe('webhook SSRF guard (unit)', () => {
  it('rejects http:// webhook URLs', async () => {
    const { sendWebhook: realWebhook } =
      jest.requireActual<typeof import('../src/channels/webhook')>(
        '../src/channels/webhook',
      );

    mockSendWebhook.mockImplementationOnce(realWebhook);

    const msg = envelope('notification.send', {
      channel: 'webhook',
      to: 'http://evil.example.com/exfil',
      message: 'data',
    });

    await expect(handleKafkaMessage('nexus.notifications', msg)).resolves.toBeUndefined();
  });
});
