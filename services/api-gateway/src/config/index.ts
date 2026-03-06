function requireEnv(key: string): string {
  const value = process.env[key];
  if (!value) {
    throw new Error(`Missing required environment variable: ${key}`);
  }
  return value;
}

function optionalEnv(key: string, defaultValue: string): string {
  return process.env[key] ?? defaultValue;
}

function optionalInt(key: string, defaultValue: number): number {
  const raw = process.env[key];
  if (!raw) return defaultValue;
  const parsed = parseInt(raw, 10);
  if (isNaN(parsed)) {
    throw new Error(`Environment variable ${key} must be an integer, got: "${raw}"`);
  }
  return parsed;
}

function optionalFloat(key: string, defaultValue: number): number {
  const raw = process.env[key];
  if (!raw) return defaultValue;
  const parsed = parseFloat(raw);
  if (isNaN(parsed)) {
    throw new Error(`Environment variable ${key} must be a number, got: "${raw}"`);
  }
  return parsed;
}

export const config = Object.freeze({
  environment: optionalEnv('ENVIRONMENT', 'development'),
  port: optionalInt('API_GATEWAY_PORT', 3000),
  logLevel: optionalEnv('API_GATEWAY_LOG_LEVEL', 'info'),

  upstreams: {
    settlement: requireEnv('SETTLEMENT_SERVICE_URL'),
    fraud: requireEnv('FRAUD_DETECTION_URL'),
    notification: requireEnv('NOTIFICATION_SERVICE_URL'),
  },

  redisUrl: requireEnv('REDIS_URL'),

  rateLimit: {
    windowMs: optionalInt('RATE_LIMIT_WINDOW_MS', 60_000),
    maxRequests: optionalInt('RATE_LIMIT_MAX_REQUESTS', 100),
  },

  jwt: {

    publicKeyBase64: requireEnv('JWT_PUBLIC_KEY_BASE64'),
    algorithm: 'RS256' as const,
    accessTokenExpireMinutes: optionalInt('JWT_ACCESS_TOKEN_EXPIRE_MINUTES', 15),
  },

  cors: {

    allowedOrigins: optionalEnv('CORS_ALLOWED_ORIGINS', 'http://localhost:3000').split(','),
  },

  circuitBreaker: {
    timeout: optionalInt('CB_TIMEOUT_MS', 3_000),
    errorThresholdPercentage: optionalFloat('CB_ERROR_THRESHOLD_PCT', 50),
    resetTimeout: optionalInt('CB_RESET_TIMEOUT_MS', 30_000),
  },
} as const);
