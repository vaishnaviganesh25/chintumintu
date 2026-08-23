import type {
  DecisionRecord,
  DisputeRecord,
  DisputeOutcome,
  OperatingStats,
  DeepHealth,
} from '../types';
import { API_BASE_URL, FraudApiError } from './fraudApi';

/**
 * Client for the ledger, disposition, dispute and deep-health endpoints.
 *
 * Kept apart from `fraudApi.ts` on purpose. That module is the scoring path and is on
 * the critical path of the demo; this one drives the operations console, and a failure
 * here must never be able to stop a payment being scored. Different blast radius,
 * different file.
 */

const OPS_TIMEOUT_MS = 10_000;
// Drafting a representment packet calls a language model, which is slower than
// anything else in the product by an order of magnitude.
const DISPUTE_TIMEOUT_MS = 120_000;

async function request<T>(
  path: string,
  init: RequestInit = {},
  timeoutMs: number = OPS_TIMEOUT_MS,
  signal?: AbortSignal,
): Promise<T> {
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

  const forward = () => controller.abort();
  signal?.addEventListener('abort', forward, { once: true });

  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      signal: controller.signal,
      headers: { 'Content-Type': 'application/json', ...(init.headers ?? {}) },
    });

    if (!response.ok) {
      let detail: string | undefined;
      try {
        detail = (await response.json())?.detail;
      } catch {
        detail = undefined;
      }
      throw new FraudApiError(
        typeof detail === 'string' && detail.trim()
          ? detail
          : `${response.status} ${response.statusText || 'request failed'}`,
        response.status,
      );
    }

    return (await response.json()) as T;
  } catch (error) {
    if (timedOut) {
      throw new FraudApiError(
        `The API did not respond within ${Math.round(timeoutMs / 1000)}s.`,
      );
    }
    if (signal?.aborted) throw error;
    if (error instanceof TypeError) {
      throw new FraudApiError(
        `Cannot reach the FinGuard API at ${API_BASE_URL}. Start it with \`python main.py\`.`,
      );
    }
    throw error;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', forward);
  }
}

/**
 * The work queue: payments held or challenged, newest first.
 *
 * `only_actioned` rather than a single status literal — the API emits three actions,
 * and a queue filtered on one of them silently returns nothing, which reads as a quiet
 * day rather than a broken filter.
 */
export async function fetchQueue(
  limit = 25,
  signal?: AbortSignal,
): Promise<DecisionRecord[]> {
  const body = await request<{ decisions: DecisionRecord[] }>(
    `/api/v1/decisions?only_actioned=true&limit=${limit}`,
    {},
    OPS_TIMEOUT_MS,
    signal,
  );
  return body.decisions ?? [];
}

/** One decision replayed in full, with every disposition recorded against it. */
export function fetchDecision(
  decisionId: string,
  signal?: AbortSignal,
): Promise<DecisionRecord> {
  return request<DecisionRecord>(`/api/v1/decisions/${decisionId}`, {}, OPS_TIMEOUT_MS, signal);
}

/** Attach a reviewer's conclusion. Appends — it never rewrites the decision. */
export function recordDisposition(
  decisionId: string,
  outcome: DisputeOutcome,
  reviewer = 'dashboard',
  signal?: AbortSignal,
): Promise<unknown> {
  return request(
    `/api/v1/decisions/${decisionId}/disposition`,
    { method: 'POST', body: JSON.stringify({ outcome, reviewer }) },
    OPS_TIMEOUT_MS,
    signal,
  );
}

/** Raise a chargeback and get the drafted representment packet back. */
export function raiseDispute(
  decisionId: string,
  disputeReason: string,
  signal?: AbortSignal,
): Promise<DisputeRecord> {
  return request<DisputeRecord>(
    '/api/v1/disputes',
    { method: 'POST', body: JSON.stringify({ decision_id: decisionId, dispute_reason: disputeReason }) },
    DISPUTE_TIMEOUT_MS,
    signal,
  );
}

/**
 * Operating summary. Returns null rather than throwing — a stats strip that breaks the
 * page when the ledger is unavailable is worse than one that quietly empties.
 */
export async function fetchStats(signal?: AbortSignal): Promise<OperatingStats | null> {
  try {
    return await request<OperatingStats>('/api/v1/stats', {}, OPS_TIMEOUT_MS, signal);
  } catch {
    return null;
  }
}

/**
 * Per-dependency status and the active degradation rung.
 *
 * This is what makes a silent fallback visible: the shallow probe answers "is it up",
 * this one answers "what can it currently do".
 */
export async function fetchDeepHealth(signal?: AbortSignal): Promise<DeepHealth | null> {
  try {
    return await request<DeepHealth>('/api/v1/health/deep', {}, OPS_TIMEOUT_MS, signal);
  } catch {
    return null;
  }
}

/** Disable or restore the model, to demonstrate the ladder. 403 unless enabled server-side. */
export function setModelDisabled(disable: boolean, signal?: AbortSignal): Promise<unknown> {
  return request(
    `/api/v1/admin/chaos/model?disable=${disable}`,
    { method: 'POST' },
    OPS_TIMEOUT_MS,
    signal,
  );
}
