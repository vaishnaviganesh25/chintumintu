/**
 * Formats probability as percentage string
 */
export function formatProbabilityAsPercentage(probability: number): string {
  return `${(probability * 100).toFixed(0)}%`;
}

/**
 * Formats execution time as latency string
 */
export function formatLatency(timeMs: number): string {
  return `Inference Time: ${timeMs}ms`;
}

/**
 * Formats SHAP importance for tooltip display
 */
export function formatImportanceForTooltip(importance: number): string {
  return `${(importance * 100).toFixed(1)}%`;
}