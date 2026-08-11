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
}

/**
 * Response from POST /api/v1/analyze-transaction
 */
export interface FraudDetectionResponse {
  transaction_id: string; // Unique transaction identifier
  status: 'BLOCKED' | 'APPROVED'; // Decision at the model's calibrated threshold
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
}

/**
 * Application state (managed in the useFraudSimulation hook)
 */
export interface DashboardState {
  isLoading: boolean;
  results: FraudDetectionResponse | null;
  error: string | null;
}
