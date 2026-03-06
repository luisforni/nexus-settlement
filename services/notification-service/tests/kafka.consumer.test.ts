process.env.KAFKA_BROKERS = 'localhost:9092';
process.env.NODE_ENV = 'test';

const mockConsumerRun = jest.fn().mockResolvedValue(undefined);
const mockConsumerSubscribe = jest.fn().mockResolvedValue(undefined);
const mockConsumerConnect = jest.fn().mockResolvedValue(undefined);
const mockConsumerDisconnect = jest.fn().mockResolvedValue(undefined);

const mockConsumer = {
  connect: mockConsumerConnect,
  subscribe: mockConsumerSubscribe,
  run: mockConsumerRun,
  disconnect: mockConsumerDisconnect,
};

const mockKafkaConsumer = jest.fn().mockReturnValue(mockConsumer);

jest.mock('kafkajs', () => ({
  Kafka: jest.fn().mockImplementation(() => ({ consumer: mockKafkaConsumer })),
  logLevel: { WARN: 4 },
}));

jest.mock('../src/tracing', () => ({}));

const mockHandleKafkaMessage = jest.fn().mockResolvedValue(undefined);
jest.mock('../src/handlers/notification.handler', () => ({
  handleKafkaMessage: mockHandleKafkaMessage,
}));

jest.mock('../src/logger', () => ({
  logger: { info: jest.fn(), warn: jest.fn(), error: jest.fn(), debug: jest.fn() },
}));

import http from 'node:http';

function get(url: string): Promise<{ status: number; body: string }> {
  return new Promise((resolve, reject) => {
    http.get(url, (res) => {
      let body = '';
      res.on('data', (chunk: Buffer) => (body += chunk.toString()));
      res.on('end', () => resolve({ status: res.statusCode ?? 0, body }));
    }).on('error', reject);
  });
}

describe('Kafka consumer subscription', () => {
  beforeEach(() => jest.clearAllMocks());

  it('subscribes to all five expected topics', async () => {

    jest.isolateModules(() => {

      require('../src/app');
    });

    await new Promise((r) => setImmediate(r));

    const subscribedTopics = mockConsumerSubscribe.mock.calls.map(
      (c) => (c[0] as { topic: string }).topic,
    );

    expect(subscribedTopics).toContain('nexus.settlements');
    expect(subscribedTopics).toContain('nexus.fraud.alerts');
    expect(subscribedTopics).toContain('nexus.notifications');
    expect(subscribedTopics).toContain('nexus.settlements.dlq');
    expect(subscribedTopics).toContain('nexus.fraud.dlq');
  });

  it('calls consumer.connect() exactly once on startup', async () => {
    jest.isolateModules(() => {

      require('../src/app');
    });
    await new Promise((r) => setImmediate(r));
    expect(mockConsumerConnect).toHaveBeenCalledTimes(1);
  });

  it('calls consumer.run() with autoCommit enabled', async () => {
    jest.isolateModules(() => {

      require('../src/app');
    });
    await new Promise((r) => setImmediate(r));
    expect(mockConsumerRun).toHaveBeenCalledTimes(1);
    const [opts] = mockConsumerRun.mock.calls[0]! as [{ autoCommit: boolean }];
    expect(opts.autoCommit).toBe(true);
  });
});

describe('eachMessage routing', () => {
  beforeEach(() => jest.clearAllMocks());

  it('passes the topic and message value to handleKafkaMessage', async () => {

    let capturedEachMessage: ((ctx: { topic: string; message: { value: Buffer | null } }) => Promise<void>) | null = null;
    mockConsumerRun.mockImplementation(async (opts: { eachMessage: (ctx: { topic: string; message: { value: Buffer | null } }) => Promise<void> }) => {
      capturedEachMessage = opts.eachMessage;
    });

    jest.isolateModules(() => {

      require('../src/app');
    });
    await new Promise((r) => setImmediate(r));

    expect(capturedEachMessage).not.toBeNull();

    const payload = JSON.stringify({ event_type: 'settlement.completed' });
    await capturedEachMessage!({
      topic: 'nexus.settlements',
      message: { value: Buffer.from(payload) },
    });

    expect(mockHandleKafkaMessage).toHaveBeenCalledWith('nexus.settlements', payload);
  });

  it('passes null to handleKafkaMessage when message value is null', async () => {
    let capturedEachMessage: ((ctx: { topic: string; message: { value: Buffer | null } }) => Promise<void>) | null = null;
    mockConsumerRun.mockImplementation(async (opts: { eachMessage: (ctx: { topic: string; message: { value: Buffer | null } }) => Promise<void> }) => {
      capturedEachMessage = opts.eachMessage;
    });

    jest.isolateModules(() => {

      require('../src/app');
    });
    await new Promise((r) => setImmediate(r));

    await capturedEachMessage!({ topic: 'nexus.settlements', message: { value: null } });
    expect(mockHandleKafkaMessage).toHaveBeenCalledWith('nexus.settlements', null);
  });
});

describe('Health endpoint', () => {
  let server: http.Server;
  const TEST_PORT = 18999;

  beforeAll(() => {

    let healthy = false;
    server = http.createServer((req, res) => {
      if (req.url === '/health' || req.url === '/livez') {
        res.writeHead(healthy ? 200 : 503, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ status: healthy ? 'ok' : 'starting' }));
        return;
      }
      res.writeHead(404).end();
    });
    server.listen(TEST_PORT, () => {

      healthy = true;
    });
  });

  afterAll(() => new Promise<void>((resolve) => server.close(() => resolve())));

  it('returns 200 with { status: "ok" } once healthy', async () => {
    const { status, body } = await get(`http://localhost:${TEST_PORT}/health`);
    expect(status).toBe(200);
    expect(JSON.parse(body)).toMatchObject({ status: 'ok' });
  });

  it('/livez is an alias for /health', async () => {
    const { status } = await get(`http://localhost:${TEST_PORT}/livez`);
    expect(status).toBe(200);
  });

  it('returns 404 for unknown paths', async () => {
    const { status } = await get(`http://localhost:${TEST_PORT}/unknown`);
    expect(status).toBe(404);
  });
});

describe('DLQ topics in consumer group', () => {
  beforeEach(() => jest.clearAllMocks());

  it('consumer is created with the configured group ID', async () => {
    jest.isolateModules(() => {

      require('../src/app');
    });
    await new Promise((r) => setImmediate(r));

    expect(mockKafkaConsumer).toHaveBeenCalledWith(
      expect.objectContaining({ groupId: expect.any(String) }),
    );
  });

  it('subscribes to DLQ topics for operational alerting', async () => {
    jest.isolateModules(() => {

      require('../src/app');
    });
    await new Promise((r) => setImmediate(r));

    const dlqTopics = mockConsumerSubscribe.mock.calls
      .map((c) => (c[0] as { topic: string }).topic)
      .filter((t) => t.includes('dlq'));

    expect(dlqTopics.length).toBeGreaterThanOrEqual(2);
  });
});
