import type {
  ApiHealth,
  FraudDetectionResponse,
  MerchantAction,
  SHAPFeature,
  TransactionInput,
} from '../types';

/**
 * Client for the FinGuard Module 4 API (FastAPI, see ../../main.py).
 *
 * Everything crossing this boundary is treated as untrusted: the response is shape
 * checked before it reaches React, and every failure mode is turned into a message
 * that says what to do about it. "Failed to fetch" in a toast helps nobody.
 */

export const API_BASE_URL: string =
  import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8080';

const ANALYZE_ENDPOINT = `${API_BASE_URL}/api/v1/analyze-transaction`;
const HEALTH_ENDPOINT = `${API_BASE_URL}/api/v1/health`;

/** Scoring is ~50-120 ms; anything near this ceiling means something is wrong. */
const REQUEST_TIMEOUT_MS = 15_000;
const HEALTH_TIMEOUT_MS = 4_000;

export class FraudApiError extends Error {
  readonly status?: number;

  constructor(message: string, status?: number) {
    super(message);
    this.name = 'FraudApiError';
    this.status = status;
  }
}

/** One entry of FastAPI's 422 body. */
interface ValidationDetail {
  loc?: unknown[];
  msg?: string;
}

/**
 * Turn FastAPI's validation payload into something a person can act on.
 *
 * The raw form is a list of `{loc: ["body", "sender_vpa"], msg: "Value error, ..."}`,
 * which is precise and unreadable. This produces "sender_vpa: must be a valid UPI VPA".
 */
function formatValidationDetail(detail: ValidationDetail[]): string {
  return detail
    .map((item) => {
      const field = Array.isArray(item.loc)
        ? item.loc.filter((part) => part !== 'body').join('.')
        : '';
      const message = (item.msg ?? 'is invalid').replace(/^Value error,\s*/, '');
      return field ? `${field}: ${message}` : message;
    })
    .join('; ');
}

async function describeFailure(response: Response): Promise<string> {
  let detail: unknown;
  try {
    detail = (await response.json())?.detail;
  } catch {
    detail = undefined;
  }

  if (Array.isArray(detail)) {
    return formatValidationDetail(detail as ValidationDetail[]);
  }
  if (typeof detail === 'string' && detail.trim()) {
    return detail;
  }
  return `${response.status} ${response.statusText || 'request failed'}`;
}

function isShapFeature(value: unknown): value is SHAPFeature {
  const candidate = value as SHAPFeature | undefined;
  return (
    typeof candidate?.feature === 'string' &&
    typeof candidate?.importance === 'number' &&
    Number.isFinite(candidate.importance)
  );
}

/**
 * Verify the payload really is an analysis result before the UI renders it.
 *
 * A silent shape mismatch surfaces later as `undefined` in a chart axis, which is a
 * far harder bug to trace back to its origin than an explicit error here.
 */
function parseAnalysis(payload: unknown): FraudDetectionResponse {
  const data = payload as Partial<FraudDetectionResponse> | null;

  if (
    !data ||
    typeof data.transaction_id !== 'string' ||
    typeof data.fraud_probability !== 'number' ||
    typeof data.xai_explanation !== 'string' ||
    !Array.isArray(data.shap_features)
  ) {
    throw new FraudApiError(
      'The API returned an unexpected response shape. Check that the backend is FinGuard and not another service on this port.',
    );
  }

  // An older backend has no `action`; derive one from `status` rather than rendering
  // an empty badge. A dashboard pointed at a stale API should degrade, not break.
  const action: MerchantAction =
    data.action === 'ACCEPT' || data.action === 'STEP_UP' || data.action === 'HOLD'
      ? data.action
      : data.status === 'BLOCKED'
        ? 'HOLD'
        : 'ACCEPT';

  return {
    transaction_id: data.transaction_id,
    action,
    action_costs:
      data.action_costs && typeof data.action_costs === 'object' ? data.action_costs : {},
    status: data.status === 'BLOCKED' ? 'BLOCKED' : 'APPROVED',
    fraud_probability: data.fraud_probability,
    execution_time_ms:
      typeof data.execution_time_ms === 'number' ? data.execution_time_ms : 0,
    xai_explanation: data.xai_explanation,
    shap_features: data.shap_features.filter(isShapFeature),
    // Optional on the wire: an older backend omits them, and the UI degrades to not
    // showing the corresponding detail rather than rendering `undefined`.
    decision_id: typeof data.decision_id === 'string' ? data.decision_id : null,
    rung: typeof data.rung === 'string' ? data.rung : undefined,
    degraded: data.degraded === true,
    network_reasons: Array.isArray(data.network_reasons)
      ? data.network_reasons.filter((r): r is string => typeof r === 'string')
      : [],
    network_reputation:
      data.network_reputation && typeof data.network_reputation === 'object'
        ? data.network_reputation
        : {},
  };
}

/**
 * Run `fetch` under a timeout, while still honouring a caller-supplied abort signal.
 *
 * Built by hand rather than with `AbortSignal.any`, which is recent enough that
 * pinning the behaviour here is cheaper than discovering it missing in a test runner.
 */
async function fetchWithTimeout(
  url: string,
  init: RequestInit,
  timeoutMs: number,
  externalSignal?: AbortSignal,
): Promise<Response> {
  const controller = new AbortController();
  let timedOut = false;

  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

  const forwardAbort = () => controller.abort();
  externalSignal?.addEventListener('abort', forwardAbort, { once: true });

  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } catch (error) {
    if (timedOut) {
      throw new FraudApiError(
        `The API did not respond within ${timeoutMs / 1000}s. It may still be loading the model.`,
      );
    }
    // An abort the caller asked for is not an error - let it propagate untouched so
    // the hook can recognise it and leave the UI alone.
    if (externalSignal?.aborted) {
      throw error;
    }
    // fetch rejects with TypeError for DNS failures, refused connections and CORS
    // rejections alike. By far the most common cause here is a backend that is not
    // running, so lead with that.
    if (error instanceof TypeError) {
      throw new FraudApiError(
        `Cannot reach the FinGuard API at ${API_BASE_URL}. Start it with \`python main.py\` and check CORS allows this origin.`,
      );
    }
    throw error;
  } finally {
    clearTimeout(timer);
    externalSignal?.removeEventListener('abort', forwardAbort);
  }
}

/**
 * Score one transaction and return the model's decision with its explanation.
 *
 * `receiverVpaAgeDays` is optional but worth sending: it is the model's strongest
 * single feature, and the backend falls back to "established account" when it is
 * absent, which biases towards approving.
 */
export async function analyzeTransaction(
  input: TransactionInput,
  signal?: AbortSignal,
): Promise<FraudDetectionResponse> {
  const body: Record<string, unknown> = {
    sender_vpa: input.senderVPA.trim(),
    receiver_vpa: input.receiverVPA.trim(),
    amount: input.amount,
  };

  // Every optional field is omitted rather than sent as null, so the API applies its
  // own documented default instead of receiving an explicit "unknown".
  if (typeof input.receiverVpaAgeDays === 'number') {
    body.receiver_vpa_age_days = input.receiverVpaAgeDays;
  }

  // Sent as a naive local string on purpose. The model reads hour-of-day straight
  // off the timestamp, and serialising a Date here would hand the backend a UTC
  // instant - turning a 02:00 IST payment into 20:30 the previous day and losing
  // the odd-hour signal that one of the three scam signatures depends on.
  if (input.timestamp) {
    body.timestamp = input.timestamp;
  }

  if (input.senderCity?.trim()) {
    body.sender_city = input.senderCity.trim();
  }

  if (typeof input.timeSinceLastTxnSec === 'number') {
    body.time_since_last_txn_sec = input.timeSinceLastTxnSec;
  }

  const response = await fetchWithTimeout(
    ANALYZE_ENDPOINT,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
    REQUEST_TIMEOUT_MS,
    signal,
  );

  if (!response.ok) {
    throw new FraudApiError(await describeFailure(response), response.status);
  }

  return parseAnalysis(await response.json());
}

/**
 * Ask the API which model is loaded and at what threshold.
 *
 * Used for the header indicator. Returns null instead of throwing: a failed health
 * probe should show a disconnected badge, never break the page.
 */
export async function fetchHealth(signal?: AbortSignal): Promise<ApiHealth | null> {
  try {
    const response = await fetchWithTimeout(
      HEALTH_ENDPOINT,
      { method: 'GET' },
      HEALTH_TIMEOUT_MS,
      signal,
    );
    if (!response.ok) return null;

    const data = (await response.json()) as Partial<ApiHealth> | null;
    if (!data || typeof data.status !== 'string') return null;

    return {
      status: data.status,
      model_loaded: Boolean(data.model_loaded),
      model_name: data.model_name ?? null,
      threshold: typeof data.threshold === 'number' ? data.threshold : null,
      trained_at: data.trained_at ?? null,
    };
  } catch {
    return null;
  }
}
