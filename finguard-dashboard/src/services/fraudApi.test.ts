import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { analyzeTransaction, fetchHealth, FraudApiError } from './fraudApi';
import type { TransactionInput } from '../types';

const input: TransactionInput = {
  senderVPA: 'user@ybl',
  receiverVPA: 'merchant@paytm',
  amount: 1000,
};

/** A realistic body from POST /api/v1/analyze-transaction. */
const apiResponse = {
  transaction_id: 'tx-0eb747b1709c',
  status: 'BLOCKED',
  fraud_probability: 0.9823,
  execution_time_ms: 82,
  xai_explanation: 'We have paused a payment of Rs.62,000 from your account for your safety.',
  shap_features: [
    { feature: 'age of the receiving UPI ID', importance: 0.2115 },
    { feature: 'transaction amount', importance: 0.1321 },
    { feature: 'jump in size versus the previous payment', importance: -0.0307 },
  ],
};

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? 'OK' : 'Error',
    json: async () => body,
  } as Response;
}

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('analyzeTransaction', () => {
  it('POSTs snake_case fields to the analyze endpoint', async () => {
    fetchMock.mockResolvedValue(jsonResponse(apiResponse));

    await analyzeTransaction(input);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('http://localhost:8080/api/v1/analyze-transaction');
    expect(init.method).toBe('POST');
    expect(init.headers).toMatchObject({ 'Content-Type': 'application/json' });
    expect(JSON.parse(init.body)).toEqual({
      sender_vpa: 'user@ybl',
      receiver_vpa: 'merchant@paytm',
      amount: 1000,
    });
  });

  it('includes receiver_vpa_age_days only when supplied', async () => {
    fetchMock.mockResolvedValue(jsonResponse(apiResponse));

    await analyzeTransaction({ ...input, receiverVpaAgeDays: 0 });

    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toMatchObject({
      receiver_vpa_age_days: 0,
    });
  });

  it('returns the parsed analysis, preserving negative SHAP contributions', async () => {
    fetchMock.mockResolvedValue(jsonResponse(apiResponse));

    const result = await analyzeTransaction(input);

    expect(result.status).toBe('BLOCKED');
    expect(result.fraud_probability).toBeCloseTo(0.9823);
    expect(result.shap_features).toHaveLength(3);
    expect(result.shap_features[2].importance).toBeLessThan(0);
  });

  it('trims whitespace off the VPAs before sending', async () => {
    fetchMock.mockResolvedValue(jsonResponse(apiResponse));

    await analyzeTransaction({ ...input, senderVPA: '  user@ybl  ' });

    expect(JSON.parse(fetchMock.mock.calls[0][1].body).sender_vpa).toBe('user@ybl');
  });

  it('flattens a FastAPI 422 body into a readable message', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        {
          detail: [
            {
              type: 'value_error',
              loc: ['body', 'sender_vpa'],
              msg: 'Value error, must be a valid UPI VPA of the form name@handle',
            },
          ],
        },
        422,
      ),
    );

    await expect(analyzeTransaction(input)).rejects.toThrow(
      'sender_vpa: must be a valid UPI VPA of the form name@handle',
    );
  });

  it('surfaces the detail string from a 503 when the model is not loaded', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ detail: 'Model artifacts are not loaded.' }, 503),
    );

    await expect(analyzeTransaction(input)).rejects.toMatchObject({
      name: 'FraudApiError',
      status: 503,
      message: 'Model artifacts are not loaded.',
    });
  });

  it('explains an unreachable backend rather than reporting "failed to fetch"', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));

    await expect(analyzeTransaction(input)).rejects.toThrow(/Cannot reach the FinGuard API/);
  });

  it('rejects a response that is not shaped like an analysis', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ hello: 'world' }));

    await expect(analyzeTransaction(input)).rejects.toBeInstanceOf(FraudApiError);
  });

  it('propagates a caller-initiated abort without rewriting it', async () => {
    const controller = new AbortController();
    const abortError = new DOMException('Aborted', 'AbortError');
    fetchMock.mockImplementation(() => {
      controller.abort();
      return Promise.reject(abortError);
    });

    await expect(analyzeTransaction(input, controller.signal)).rejects.toBe(abortError);
  });
});

describe('fetchHealth', () => {
  it('normalises a healthy payload', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        status: 'ok',
        model_loaded: true,
        model_name: 'RandomForest',
        threshold: 0.123,
        trained_at: '2026-08-11T12:23:10+00:00',
      }),
    );

    await expect(fetchHealth()).resolves.toMatchObject({
      model_loaded: true,
      model_name: 'RandomForest',
      threshold: 0.123,
    });
  });

  it('returns null instead of throwing when the API is down', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));

    await expect(fetchHealth()).resolves.toBeNull();
  });
});
