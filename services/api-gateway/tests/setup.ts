import crypto from 'crypto';

const { publicKey, privateKey } = crypto.generateKeyPairSync('rsa', {
  modulusLength: 2048,
});

const publicKeyPem = publicKey.export({ type: 'pkcs1', format: 'pem' }) as string;
const privateKeyPem = privateKey.export({ type: 'pkcs1', format: 'pem' }) as string;

process.env['NODE_ENV'] = 'test';

process.env['JWT_PUBLIC_KEY_BASE64'] = Buffer.from(publicKeyPem).toString('base64');
process.env['TEST_PRIVATE_KEY'] = privateKeyPem;

process.env['SETTLEMENT_SERVICE_URL'] = 'http://settlement-service:8001';
process.env['FRAUD_DETECTION_URL'] = 'http://fraud-detection:8002';
process.env['NOTIFICATION_SERVICE_URL'] = 'http://notification-service:8003';
process.env['REDIS_URL'] = 'redis://redis:6379';
