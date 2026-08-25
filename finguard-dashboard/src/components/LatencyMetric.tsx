import { motion } from 'framer-motion';
import { Icon } from './Icon';

interface LatencyMetricProps {
  executionTimeMs: number;
}

/**
 * Scoring latency for one payment.
 *
 * Worth surfacing rather than hiding: a risk decision sits in the authorisation path,
 * so the number is a product constraint and not a vanity metric. The threshold is
 * 100 ms because that is roughly where a synchronous check starts being felt by the
 * customer waiting on the other side.
 */
const BUDGET_MS = 100;

export function LatencyMetric({ executionTimeMs }: LatencyMetricProps) {
  const withinBudget = executionTimeMs < BUDGET_MS;
  const tone = withinBudget ? 'var(--accept)' : 'var(--challenge)';
  const soft = withinBudget ? 'var(--accept-soft)' : 'var(--challenge-soft)';

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.2, duration: 0.35 }}
      className="inline-flex items-center gap-1.5 fg-mono"
      style={{
        fontSize: 11.5,
        color: tone,
        background: soft,
        border: `1px solid ${tone}`,
        borderRadius: 'var(--radius-sm)',
        padding: '3px 8px',
      }}
      title={
        withinBudget
          ? `Inside the ${BUDGET_MS} ms authorisation budget`
          : `Over the ${BUDGET_MS} ms authorisation budget`
      }
    >
      <Icon name="clock" size={13} />
      {executionTimeMs} ms
    </motion.div>
  );
}
