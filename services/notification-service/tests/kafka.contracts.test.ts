import Ajv from 'ajv';
import addFormats from 'ajv-formats';
import * as fs from 'node:fs';
import * as path from 'node:path';

const CONTRACTS_DIR = path.resolve(__dirname, '../../../shared/contracts');

function loadSchema(filename: string): object {
  return JSON.parse(fs.readFileSync(path.join(CONTRACTS_DIR, filename), 'utf-8')) as object;
}

const settlementSchema = loadSchema('settlement-event.json');
const fraudSchema = loadSchema('fraud-alert-event.json');

const ajv = new Ajv({ strict: false, allErrors: true });
addFormats(ajv);

const validateSettlement = ajv.compile(settlementSchema);
const validateFraud = ajv.compile(fraudSchema);

const UUID = '550e8400-e29b-41d4-a716-446655440000';
const HASH = 'a'.repeat(64);

function settlementEvent(
  overrides: Partial<Record<string, unknown>> = {},
  payloadOverrides: Partial<Record<string, unknown>> = {},
): Record<string, unknown> {
  return {
    event_id: UUID,
    event_type: 'settlement.completed',
    schema_version: '1.0.0',
    timestamp: '2026-03-10T12:00:00Z',
    integrity_hash: HASH,
    payload: {
      settlement_id: UUID,
      status: 'COMPLETED',
      amount: '100.00',
      currency: 'USD',
      payer_id: UUID,
      payee_id: UUID,
      ...payloadOverrides,
    },
    ...overrides,
  };
}

function fraudEvent(
  overrides: Partial<Record<string, unknown>> = {},
  payloadOverrides: Partial<Record<string, unknown>> = {},
): Record<string, unknown> {
  return {
    event_id: UUID,
    event_type: 'fraud.scored',
    schema_version: '1.0.0',
    timestamp: '2026-03-10T12:00:00Z',
    payload: {
      transaction_id: UUID,
      settlement_id: UUID,
      risk_score: 0.12,
      decision: 'APPROVE',
      model_version: 'xgb-v1.2.0',
      features_used: 18,
      ...payloadOverrides,
    },
    ...overrides,
  };
}

describe('Settlement event schema', () => {
  describe('valid events', () => {
    test.each([
      ['settlement.created', 'PENDING'],
      ['settlement.processing', 'PROCESSING'],
      ['settlement.completed', 'COMPLETED'],
      ['settlement.failed', 'FAILED'],
      ['settlement.cancelled', 'CANCELLED'],
      ['settlement.reversed', 'REVERSED'],
    ] as const)('accepts %s / %s', (eventType, status) => {
      const valid = validateSettlement(settlementEvent({ event_type: eventType }, { status }));
      expect(valid).toBe(true);
    });

    test.each(['0.01', '100.00', '9999999.99', '0.12345678'])(
      'accepts amount format %s',
      (amount) => {
        expect(validateSettlement(settlementEvent({}, { amount }))).toBe(true);
      },
    );

    test.each(['USD', 'EUR', 'GBP', 'JPY'])('accepts ISO-4217 currency %s', (currency) => {
      expect(validateSettlement(settlementEvent({}, { currency }))).toBe(true);
    });

    it('accepts optional fields (risk_score, user_email, description)', () => {
      const event = settlementEvent(
        {},
        {
          description: 'Test payment',
          risk_score: 0.42,
          fraud_decision: 'APPROVE',
          user_email: 'user@example.com',
          version: 2,
        },
      );
      expect(validateSettlement(event)).toBe(true);
    });

    it('accepts idempotency_key at the envelope level', () => {
      expect(validateSettlement(settlementEvent({ idempotency_key: 'key-123' }))).toBe(true);
    });
  });

  describe('invalid events', () => {
    it('rejects missing event_id', () => {
      const { event_id: _, ...event } = settlementEvent();
      expect(validateSettlement(event)).toBe(false);
    });

    it('rejects missing integrity_hash', () => {
      const { integrity_hash: _, ...event } = settlementEvent();
      expect(validateSettlement(event)).toBe(false);
    });

    it('rejects unknown event_type', () => {
      expect(validateSettlement(settlementEvent({ event_type: 'settlement.invented' }))).toBe(false);
    });

    it('rejects invalid UUID event_id', () => {
      expect(validateSettlement(settlementEvent({ event_id: 'not-a-uuid' }))).toBe(false);
    });

    it('rejects integrity_hash of wrong length', () => {
      expect(validateSettlement(settlementEvent({ integrity_hash: 'abc' }))).toBe(false);
    });

    test.each(['100', '-50.00', 'abc', '100.1', '100.123456789'])(
      'rejects invalid amount %s',
      (amount) => {
        expect(validateSettlement(settlementEvent({}, { amount }))).toBe(false);
      },
    );

    test.each(['us', 'USDT', '123', ''])('rejects invalid currency %s', (currency) => {
      expect(validateSettlement(settlementEvent({}, { currency }))).toBe(false);
    });

    it('rejects unknown status', () => {
      expect(validateSettlement(settlementEvent({}, { status: 'UNKNOWN' }))).toBe(false);
    });

    it('rejects risk_score > 1', () => {
      expect(validateSettlement(settlementEvent({}, { risk_score: 1.5 }))).toBe(false);
    });

    it('rejects description longer than 255 chars', () => {
      expect(
        validateSettlement(settlementEvent({}, { description: 'x'.repeat(256) })),
      ).toBe(false);
    });

    it('rejects additional top-level properties', () => {
      expect(validateSettlement(settlementEvent({ unexpected: 'value' }))).toBe(false);
    });
  });
});

describe('Fraud alert event schema', () => {
  describe('valid events', () => {
    test.each([
      ['fraud.scored', 'APPROVE', 0.1],
      ['fraud.review', 'REVIEW', 0.65],
      ['fraud.blocked', 'BLOCK', 0.92],
    ] as const)('accepts %s / %s with risk_score %d', (eventType, decision, riskScore) => {
      const valid = validateFraud(fraudEvent({ event_type: eventType }, { decision, risk_score: riskScore }));
      expect(valid).toBe(true);
    });

    test.each([0, 0.01, 0.5, 1.0])('accepts risk_score=%d', (score) => {
      expect(validateFraud(fraudEvent({}, { risk_score: score }))).toBe(true);
    });

    it('accepts top_risk_factors array (max 10 items)', () => {
      const factors = Array.from({ length: 5 }, (_, i) => ({
        feature: `feature_${i}`,
        shap_value: i * 0.1,
        contribution: 'increases_risk',
      }));
      expect(validateFraud(fraudEvent({}, { top_risk_factors: factors }))).toBe(true);
    });

    it('accepts null rule_triggered', () => {
      expect(validateFraud(fraudEvent({}, { rule_triggered: null }))).toBe(true);
    });

    it('accepts latency_ms field', () => {
      expect(validateFraud(fraudEvent({}, { latency_ms: 37 }))).toBe(true);
    });
  });

  describe('invalid events', () => {
    it('rejects unknown event_type', () => {
      expect(validateFraud(fraudEvent({ event_type: 'fraud.invented' }))).toBe(false);
    });

    it('rejects unknown decision', () => {
      expect(validateFraud(fraudEvent({}, { decision: 'ALLOW' }))).toBe(false);
    });

    test.each([-0.01, 1.01, 2.0])('rejects risk_score=%d out of range', (score) => {
      expect(validateFraud(fraudEvent({}, { risk_score: score }))).toBe(false);
    });

    it('rejects missing transaction_id', () => {
      const event = fraudEvent();
      delete (event.payload as Record<string, unknown>)['transaction_id'];
      expect(validateFraud(event)).toBe(false);
    });

    it('rejects missing model_version', () => {
      const event = fraudEvent();
      delete (event.payload as Record<string, unknown>)['model_version'];
      expect(validateFraud(event)).toBe(false);
    });

    it('rejects features_used = 0 (must be >= 1)', () => {
      expect(validateFraud(fraudEvent({}, { features_used: 0 }))).toBe(false);
    });

    it('rejects top_risk_factors with more than 10 items', () => {
      const factors = Array.from({ length: 11 }, (_, i) => ({
        feature: `f${i}`,
        shap_value: 0.1,
      }));
      expect(validateFraud(fraudEvent({}, { top_risk_factors: factors }))).toBe(false);
    });

    it('rejects additional payload properties', () => {
      expect(validateFraud(fraudEvent({}, { undocumented: 'value' }))).toBe(false);
    });
  });
});
