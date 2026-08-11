/**
 * Gets color for risk gauge based on probability thresholds
 */
export function getRiskGaugeColor(probability: number): string {
  if (probability > 0.70) return 'red';
  if (probability >= 0.40) return 'yellow';
  return 'green';
}

/**
 * Gets color for latency metric based on execution time
 */
export function getLatencyColor(timeMs: number): string {
  return timeMs < 100 ? 'green' : 'yellow';
}