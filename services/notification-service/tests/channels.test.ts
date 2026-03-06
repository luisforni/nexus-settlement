process.env.KAFKA_BROKERS = 'localhost:9092';

const mockSesSend = jest.fn().mockResolvedValue({});
jest.mock('@aws-sdk/client-ses', () => ({
  SESClient: jest.fn().mockImplementation(() => ({ send: mockSesSend })),
  SendEmailCommand: jest.fn().mockImplementation((input: unknown) => ({ _input: input })),
}));

const mockMessagesCreate = jest.fn().mockResolvedValue({ sid: 'SM_TEST_SID_001' });
jest.mock('twilio', () =>
  jest.fn().mockReturnValue({ messages: { create: mockMessagesCreate } }),
);

const mockAxiosPost = jest.fn().mockResolvedValue({ status: 200, data: {} });
jest.mock('axios', () => {
  class FakeAxiosError extends Error {
    response?: { status: number };
    constructor(
      msg: string,
      _code?: unknown,
      _conf?: unknown,
      _req?: unknown,
      response?: { status: number },
    ) {
      super(msg);
      this.name = 'AxiosError';
      if (response !== undefined) this.response = response;
    }
  }
  return {
    __esModule: true,
    default: { post: mockAxiosPost },
    AxiosError: FakeAxiosError,
  };
});

const mockConfig: {
  AWS_REGION: string;
  SES_FROM_EMAIL: string | undefined;
  TWILIO_ACCOUNT_SID: string | undefined;
  TWILIO_AUTH_TOKEN: string | undefined;
  TWILIO_FROM_NUMBER: string | undefined;
  WEBHOOK_MAX_RETRIES: number;
  WEBHOOK_TIMEOUT_MS: number;
} = {
  AWS_REGION: 'us-east-1',
  SES_FROM_EMAIL: 'no-reply@nexus.test',
  TWILIO_ACCOUNT_SID: 'AC_test_account_sid',
  TWILIO_AUTH_TOKEN: 'test_auth_token',
  TWILIO_FROM_NUMBER: '+15550000000',
  WEBHOOK_MAX_RETRIES: 1,
  WEBHOOK_TIMEOUT_MS: 3000,
};
jest.mock('../src/config', () => ({ config: mockConfig }));

jest.mock('../src/logger', () => ({
  logger: { info: jest.fn(), warn: jest.fn(), error: jest.fn(), debug: jest.fn() },
}));

import { sendEmail } from '../src/channels/email';
import { sendSms } from '../src/channels/sms';
import { sendWebhook } from '../src/channels/webhook';

beforeEach(() => {
  jest.clearAllMocks();

  mockConfig.SES_FROM_EMAIL = 'no-reply@nexus.test';
  mockConfig.TWILIO_ACCOUNT_SID = 'AC_test_account_sid';
  mockConfig.TWILIO_AUTH_TOKEN = 'test_auth_token';
  mockConfig.TWILIO_FROM_NUMBER = '+15550000000';
});

describe('sendEmail', () => {
  it('sends SES command with correct recipient, subject, and source', async () => {
    await sendEmail({ to: 'user@example.com', subject: 'Settlement complete', body: 'Done.' });

    expect(mockSesSend).toHaveBeenCalledTimes(1);
    const [cmd] = mockSesSend.mock.calls[0]!;
    const input = (cmd as { _input: Record<string, unknown> })._input as {
      Destination: { ToAddresses: string[] };
      Message: { Subject: { Data: string } };
      Source: string;
    };
    expect(input.Destination.ToAddresses).toEqual(['user@example.com']);
    expect(input.Message.Subject.Data).toBe('Settlement complete');
    expect(input.Source).toBe('no-reply@nexus.test');
  });

  it('HTML-escapes < > & " in the HTML body (XSS prevention)', async () => {
    await sendEmail({
      to: 'user@example.com',
      subject: 'XSS probe',
      body: '<script>alert("xss")</script> & \''injection\'',
    });

    const [cmd] = mockSesSend.mock.calls[0]!;
    const input = (cmd as { _input: Record<string, unknown> })._input as {
      Message: { Body: { Html: { Data: string }; Text: { Data: string } } };
    };
    const html = input.Message.Body.Html.Data;

    expect(html).not.toContain('<script>');
    expect(html).toContain('&lt;script&gt;');
    expect(html).toContain('&amp;');
    expect(html).toContain('&quot;');

    expect(input.Message.Body.Text.Data).toContain('<script>');
  });

  it('includes both HTML and plain-text body variants', async () => {
    await sendEmail({ to: 'u@example.com', subject: 'S', body: 'B' });

    const [cmd] = mockSesSend.mock.calls[0]!;
    const input = (cmd as { _input: Record<string, unknown> })._input as {
      Message: { Body: { Html: { Data: string }; Text: { Data: string } } };
    };
    expect(input.Message.Body).toHaveProperty('Html');
    expect(input.Message.Body).toHaveProperty('Text');
  });

  it('skips dispatch and does not throw when SES_FROM_EMAIL is absent', async () => {
    mockConfig.SES_FROM_EMAIL = undefined;
    await sendEmail({ to: 'x@x.com', subject: 'S', body: 'B' });
    expect(mockSesSend).not.toHaveBeenCalled();
  });
});

describe('sendSms', () => {
  it('calls Twilio messages.create with from/to/body', async () => {
    await sendSms({ to: '+15551234567', body: 'Your transfer of $100 is confirmed.' });

    expect(mockMessagesCreate).toHaveBeenCalledTimes(1);
    expect(mockMessagesCreate.mock.calls[0]![0]).toMatchObject({
      from: '+15550000000',
      to: '+15551234567',
      body: 'Your transfer of $100 is confirmed.',
    });
  });

  it('truncates body to 1600 characters (SMS GSM limit)', async () => {
    const longBody = 'X'.repeat(2500);
    await sendSms({ to: '+15551234567', body: longBody });

    const sentBody = (mockMessagesCreate.mock.calls[0]![0] as { body: string }).body;
    expect(sentBody).toHaveLength(1600);
  });

  it('does not truncate body under 1600 characters', async () => {
    const shortBody = 'Short message';
    await sendSms({ to: '+15551234567', body: shortBody });

    const sentBody = (mockMessagesCreate.mock.calls[0]![0] as { body: string }).body;
    expect(sentBody).toBe(shortBody);
  });

  it('skips dispatch and does not throw when Twilio is unconfigured', async () => {
    mockConfig.TWILIO_ACCOUNT_SID = undefined;
    mockConfig.TWILIO_AUTH_TOKEN = undefined;
    mockConfig.TWILIO_FROM_NUMBER = undefined;
    await sendSms({ to: '+15551234567', body: 'hello' });
    expect(mockMessagesCreate).not.toHaveBeenCalled();
  });
});

describe('sendWebhook — SSRF guard', () => {
  it('rejects plain HTTP URLs (must be HTTPS)', async () => {
    await expect(
      sendWebhook({ url: 'http://partner.example.com/hook', event: 'test', data: {} }),
    ).rejects.toThrow(/HTTPS/i);
    expect(mockAxiosPost).not.toHaveBeenCalled();
  });

  it('rejects localhost URLs', async () => {
    await expect(
      sendWebhook({ url: 'https://localhost/hook', event: 'test', data: {} }),
    ).rejects.toThrow(/private|loopback/i);
    expect(mockAxiosPost).not.toHaveBeenCalled();
  });

  it('rejects 127.x.x.x loopback addresses', async () => {
    await expect(
      sendWebhook({ url: 'https://127.0.0.1/hook', event: 'test', data: {} }),
    ).rejects.toThrow(/private/i);
  });

  it('rejects RFC-1918 private addresses (192.168.x.x)', async () => {
    await expect(
      sendWebhook({ url: 'https://192.168.1.100/hook', event: 'test', data: {} }),
    ).rejects.toThrow(/private/i);
  });

  it('rejects RFC-1918 private addresses (10.x.x.x)', async () => {
    await expect(
      sendWebhook({ url: 'https://10.0.0.1/hook', event: 'test', data: {} }),
    ).rejects.toThrow(/private/i);
  });

  it('rejects 172.16-31 private range', async () => {
    await expect(
      sendWebhook({ url: 'https://172.20.0.1/hook', event: 'test', data: {} }),
    ).rejects.toThrow(/private/i);
  });

  it('rejects malformed / non-parseable URLs', async () => {
    await expect(
      sendWebhook({ url: 'not-a-valid-url', event: 'test', data: {} }),
    ).rejects.toThrow(/Invalid webhook URL/i);
    expect(mockAxiosPost).not.toHaveBeenCalled();
  });
});

describe('sendWebhook — dispatch', () => {
  it('POSTs correct JSON envelope to the partner URL', async () => {
    await sendWebhook({
      url: 'https://partner.example.com/hook',
      event: 'settlement.completed',
      data: { settlement_id: 'stl_001', amount: '100.00' },
    });

    expect(mockAxiosPost).toHaveBeenCalledTimes(1);
    const [url, body, opts] = mockAxiosPost.mock.calls[0]! as [
      string,
      { event: string; timestamp: string; data: unknown },
      { headers: Record<string, string>; timeout: number },
    ];
    expect(url).toBe('https://partner.example.com/hook');
    expect(body.event).toBe('settlement.completed');
    expect(body.data).toMatchObject({ settlement_id: 'stl_001' });
    expect(typeof body.timestamp).toBe('string');
    expect(opts.headers['X-Nexus-Event']).toBe('settlement.completed');
    expect(opts.headers['Content-Type']).toBe('application/json');
  });

  it('retries once then abandons (WEBHOOK_MAX_RETRIES=1 → 2 total attempts)', async () => {
    mockAxiosPost.mockRejectedValue(new Error('ECONNREFUSED'));

    await sendWebhook({
      url: 'https://partner.example.com/hook',
      event: 'test.retry',
      data: {},
    });

    expect(mockAxiosPost).toHaveBeenCalledTimes(2);
  });

  it('succeeds on the second attempt after a transient failure', async () => {
    mockAxiosPost
      .mockRejectedValueOnce(new Error('Temporary error'))
      .mockResolvedValueOnce({ status: 200 });

    await sendWebhook({
      url: 'https://partner.example.com/hook',
      event: 'test.recovery',
      data: {},
    });

    expect(mockAxiosPost).toHaveBeenCalledTimes(2);
  });
});
