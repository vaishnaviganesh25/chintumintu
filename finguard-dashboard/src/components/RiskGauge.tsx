import { motion } from 'framer-motion';
import type { MerchantAction } from '../types';

interface RiskGaugeProps {
  probability: number; // 0.0 to 1.0
  action: MerchantAction;
  /** The model's calibrated decision threshold, from /api/v1/health. */
  threshold?: number | null;
}

/**
 * Circular fraud-risk readout.
 *
 * Colour follows the decision, not a fixed percentage band, and carries all three
 * outcomes. The merchant policy can challenge a payment at 8% risk and hold one at
 * 30%, so a dial with fixed red/amber/green bands would routinely contradict the
 * badge sitting directly above it.
 */
// Both halves come from the same token, so the number and the arc can never
// disagree about what the decision was.
const DIAL: Record<MerchantAction, string> = {
  ACCEPT: 'var(--accept)',
  STEP_UP: 'var(--challenge)',
  HOLD: 'var(--hold)',
};

export function RiskGauge({ probability, action, threshold }: RiskGaugeProps) {
  const percentage = Math.round(probability * 100);
  const tone = DIAL[action] ?? DIAL.HOLD;

  const circumference = 2 * Math.PI * 45; // radius = 45
  const strokeDashoffset = circumference - probability * circumference;

  return (
    <div className="flex flex-col items-center">
      <div className="relative w-32 h-32">
        <svg className="w-32 h-32 transform -rotate-90" viewBox="0 0 100 100">
          <circle
            cx="50"
            cy="50"
            r="45"
            stroke="currentColor"
            strokeWidth="8"
            fill="transparent"
            style={{ color: 'var(--rule)' }}
          />
          <motion.circle
            cx="50"
            cy="50"
            r="45"
            stroke={tone}
            strokeWidth="8"
            fill="transparent"
            strokeDasharray={circumference}
            strokeDashoffset={circumference}
            strokeLinecap="round"
            animate={{ strokeDashoffset }}
            transition={{ duration: 1, ease: 'easeOut' }}
          />
        </svg>

        <div className="absolute inset-0 flex items-center justify-center">
          <motion.span
            className="text-2xl font-semibold fg-mono"
            style={{ color: tone }}
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            transition={{ delay: 0.5, duration: 0.5 }}
          >
            {percentage}%
          </motion.span>
        </div>
      </div>

      <p className="fg-label mt-2">Fraud risk</p>
      {typeof threshold === 'number' && (
        <p className="fg-mono text-[11px] mt-0.5" style={{ color: 'var(--faint)' }}>
          blocks at {(threshold * 100).toFixed(1)}%
        </p>
      )}
    </div>
  );
}
