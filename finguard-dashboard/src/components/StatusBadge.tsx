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
  { label: string; hint: string; ring: string; dot: string }
> = {
  ACCEPT: {
    label: 'ACCEPT',
    hint: 'Fulfil the order',
    ring: 'bg-green-900/30 text-green-400 border-green-500',
    dot: 'bg-green-400',
  },
  STEP_UP: {
    label: 'CHALLENGE',
    hint: '3-D Secure before capture',
    ring: 'bg-amber-900/30 text-amber-300 border-amber-500',
    dot: 'bg-amber-300',
  },
  HOLD: {
    label: 'HOLD',
    hint: 'Review before fulfilment',
    ring: 'bg-red-900/30 text-red-400 border-red-500',
    dot: 'bg-red-400',
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
        className={`inline-flex items-center px-4 py-2 rounded-full text-sm font-bold border ${style.ring}`}
        role="status"
        aria-live="polite"
      >
        <span className={`w-2 h-2 rounded-full mr-2 ${style.dot}`} />
        {style.label}
      </motion.div>

      <p className="text-xs text-gray-400">{style.hint}</p>

      {ranked.length > 0 && (
        <dl className="flex flex-wrap justify-center gap-x-4 gap-y-1 text-[11px] text-gray-500">
          {ranked.map(([name, value]) => (
            <div key={name} className="flex items-center gap-1">
              <dt className={name === action ? 'text-gray-300 font-semibold' : ''}>
                {PRESENTATION[name as MerchantAction]?.label ?? name}
              </dt>
              <dd
                className={
                  name === action ? 'text-gray-300 font-semibold tabular-nums' : 'tabular-nums'
                }
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
