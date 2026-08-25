import { motion } from 'framer-motion';
import type { MerchantAction } from '../types';

interface StatusBadgeProps {
  action: MerchantAction;
  /** Expected rupee cost of each action, shown as the justification for this one. */
  costs?: Partial<Record<MerchantAction, number>>;
}

/**
 * The merchant's decision on this payment.
 *
 * Three states, not two. A gateway can challenge a payment with 3-D Secure instead of
 * declining it — costing a slice of conversion rather than the whole order — and
 * collapsing that into a red BLOCKED badge would tell the merchant to throw away a
 * sale the engine only wanted verified. Amber is its own state for that reason.
 */
const PRESENTATION: Record<
  MerchantAction,
  { label: string; hint: string; tone: string; soft: string }
> = {
  ACCEPT: {
    label: 'ACCEPT',
    hint: 'Fulfil the order',
    tone: 'var(--accept)',
    soft: 'var(--accept-soft)',
  },
  STEP_UP: {
    label: 'CHALLENGE',
    hint: '3-D Secure before capture',
    tone: 'var(--challenge)',
    soft: 'var(--challenge-soft)',
  },
  HOLD: {
    label: 'HOLD',
    hint: 'Review before fulfilment',
    tone: 'var(--hold)',
    soft: 'var(--hold-soft)',
  },
};

const formatRupees = (value: number) =>
  `₹${value.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;

export function StatusBadge({ action, costs }: StatusBadgeProps) {
  const style = PRESENTATION[action] ?? PRESENTATION.HOLD;

  // Ordered cheapest first: the chosen action should visibly be the cheapest one,
  // which is the entire justification for the decision.
  const ranked = Object.entries(costs ?? {})
    .filter(([, value]) => typeof value === 'number')
    .sort((a, b) => (a[1] as number) - (b[1] as number));

  return (
    <div className="flex flex-col items-center gap-2">
      <motion.div
        initial={{ scale: 0, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ duration: 0.4 }}
        className="inline-flex items-center gap-2 px-3 py-1.5 text-[12px] font-semibold fg-mono"
        style={{
          color: style.tone,
          background: style.soft,
          border: `1px solid ${style.tone}`,
          borderRadius: 999,
          letterSpacing: '0.06em',
        }}
        role="status"
        aria-live="polite"
      >
        <span
          style={{ width: 6, height: 6, borderRadius: 999, background: style.tone }}
        />
        {style.label}
      </motion.div>

      <p className="text-[11.5px]" style={{ color: 'var(--muted)' }}>{style.hint}</p>

      {ranked.length > 0 && (
        <dl className="flex flex-wrap justify-center gap-x-4 gap-y-1 text-[11px] fg-mono" style={{ color: 'var(--faint)' }}>
          {ranked.map(([name, value]) => (
            <div key={name} className="flex items-center gap-1">
              <dt style={{ color: name === action ? 'var(--ink)' : undefined, fontWeight: name === action ? 600 : 400 }}>
                {PRESENTATION[name as MerchantAction]?.label ?? name}
              </dt>
              <dd
                style={{
                  color: name === action ? 'var(--ink)' : undefined,
                  fontWeight: name === action ? 600 : 400,
                }}
              >
                {formatRupees(value as number)}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}
