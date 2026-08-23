/**
 * User input for transaction analysis
 */
export interface TransactionInput {
  senderVPA: string; // Format: user@provider (e.g., john@ybl)
  receiverVPA: string; // Format: user@provider (e.g., merchant@paytm)
  amount: number; // Transaction amount in INR
  /**
   * Age of the receiver's VPA in days.
   *
   * Optional, but the model's strongest single feature - a mule account is typically
   * hours old. Omitting it makes the backend assume an established account, which
   * biases every verdict towards APPROVED.
   */
  receiverVpaAgeDays?: number;
  /**
   * Transaction time as a naive local ISO string, e.g. "2026-08-23T03:12".
   *
   * Sent explicitly rather than left to the server clock: the odd-hour phishing
   * signature keys on 01:00-04:00, so a demo run at 3 PM could never produce it.
   */
  timestamp?: string;
  /** Payer's city. Feeds a one-hot feature; the API defaults it when absent. */
  senderCity?: string;
  /**
   * Seconds since this sender's previous payment, -1 for none.
   *
   * Normally derived from the API's own history store. Set it explicitly to stage
   * the second leg of a Rs.1-test without firing the first request.
   */
  timeSinceLastTxnSec?: number;
}

/**
 * Response from POST /api/v1/analyze-transaction
 */
export type MerchantAction = 'ACCEPT' | 'STEP_UP' | 'HOLD';

export interface FraudDetectionResponse {
  transaction_id: string; // Unique transaction identifier
  /**
   * The merchant-side decision: fulfil, challenge before capture, or hold for review.
   *
   * Three outcomes rather than two because a gateway can send a payment through
   * 3-D Secure, which costs a slice of conversion instead of the whole order. A bank
   * protecting a consumer has no equivalent, which is why the older `status` field
   * cannot express this on its own.
   */
  action: MerchantAction;
  /** Expected rupee cost of each action. The chosen one is the cheapest. */
  action_costs: Partial<Record<MerchantAction, number>>;
  status: 'BLOCKED' | 'APPROVED'; // Legacy two-way view of `action`
  fraud_probability: number; // Risk score (0.0 to 1.0)
  execution_time_ms: number; // Backend inference latency in milliseconds
  xai_explanation: string; // Human-readable explanation
  shap_features: SHAPFeature[]; // Per-concept contribution breakdown
}

/**
 * One concept's contribution to the score, as computed by SHAP.
 */
export interface SHAPFeature {
  /** Plain-English concept, e.g. "age of the receiving UPI ID". */
  feature: string;
  /**
   * Signed contribution, typically within roughly -0.5 to +0.5.
   *
   * Positive pushes the transaction towards fraud, negative towards legitimate.
   * These are not percentages and they do not sum to 1 - they are additive log-odds
   * style contributions that sum to the model's output, which is exactly what makes
   * them usable as an audit trail.
   */
  importance: number;
}

/**
 * Response from GET /api/v1/health
 */
export interface ApiHealth {
  status: string; // "ok" or "degraded"
  model_loaded: boolean;
  model_name: string | null;
  threshold: number | null; // Calibrated decision threshold, not 0.5
  trained_at: string | null;
}

/**
 * Form validation error state
 */
export interface ValidationErrors {
  senderVPA?: string;
  receiverVPA?: string;
  amount?: string;
  receiverVpaAgeDays?: string;
  timestamp?: string;
  timeSinceLastTxnSec?: string;
}

/**
 * Application state (managed in the useFraudSimulation hook)
 */
export interface DashboardState {
  isLoading: boolean;
  results: FraudDetectionResponse | null;
  error: string | null;
}

/**
 * A scoring decision as the ledger stored it.
 *
 * Note `fraud_probability` can be -1: that is the explicit encoding for "no model
 * produced a score", written when a fallback rung answered. A zero there would read
 * as "the model was certain it was legitimate", which is a very different claim.
 */
export interface DecisionRecord {
  decision_id: string;
  transaction_id: string;
  scored_at: string;
  sender_vpa: string;
  receiver_vpa: string;
  amount: number;
  receiver_vpa_age_days: number | null;
  txn_timestamp: string | null;
  sender_city: string | null;
  fraud_probability: number;
  threshold: number;
  decision: MerchantAction | string;
  model_name: string;
  model_trained_at: string | null;
  threshold_policy: string | null;
  latency_ms: number;
  reasons: string[];
  /** Every concept with its signed contribution — the whole vector, not the top three. */
  shap_concepts: Record<string, number>;
  dispositions?: Disposition[];
  latest_disposition?: string | null;
}

export type DisputeOutcome = 'confirmed_fraud' | 'false_positive' | 'unclear';

export interface Disposition {
  disposition_id: string;
  recorded_at: string;
  outcome: DisputeOutcome;
  reviewer: string | null;
  note: string | null;
}

export interface EvidenceItem {
  item: string;
  detail: string;
  source: string;
}

export interface RepresentmentPacket {
  reason_code: string;
  recommendation: 'represent' | 'accept_liability';
  confidence: number;
  summary: string;
  compelling_evidence: EvidenceItem[];
  argument: string;
  issuer_rebuttals: string[];
  /** Which path drafted this — a provider label, or the deterministic fallback. */
  generated_by: string;
  /** True when no model was reachable and this is a template draft needing a human pass. */
  degraded: boolean;
}

export interface DisputeRecord {
  dispute_id: string;
  decision_id: string;
  raised_at?: string;
  reason_code_label?: string;
  packet: RepresentmentPacket;
}

export interface OperatingStats {
  decisions_recorded: number;
  blocked: number;
  stepped_up: number;
  held: number;
  approved: number;
  block_rate: number;
  value_blocked_inr: number;
  avg_latency_ms: number;
  reviewed: number;
  confirmed_fraud: number;
  false_positives: number;
  unclear: number;
  /** Null until a human has judged something — never assumed for unreviewed alerts. */
  precision_reviewed: number | null;
  disputes_raised: number;
  disputes_represented: number;
  packets_drafted_degraded: number;
}

export interface DeepHealth {
  rung: number;
  rung_label: string;
  serving: boolean;
  dependencies: Record<string, { status: string; [key: string]: unknown }>;
  chaos_endpoint_enabled: boolean;
}
