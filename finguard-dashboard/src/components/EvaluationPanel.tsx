import { motion } from 'framer-motion';
import { Icon } from './Icon';
import { Badge, Notice, Panel } from './ui';
import { SPRING, useCountUp, useReducedMotion } from '../motion';
import type { FraudDetectionResponse, MerchantAction } from '../types';

/**
 * The verdict readout.
 *
 * This replaces a centred column containing a large donut and one number. The donut
 * spent most of a panel on a single scalar and could not show the thing that scalar
 * only means something against — the threshold. Worse, the three action costs were
 * rendered as a run of inline text, when comparing them *is* the entire argument this
 * project makes.
 *
 * So: risk becomes a bar with the threshold notched on it, because the interesting
 * fact is which side of the line the payment fell and by how much. Costs become
 * proportional bars, because the claim is "the chosen action is the cheapest one" and
 * a reader should be able to verify that at a glance rather than by subtracting
 * numbers in their head.
 *
 * And when the chosen action is *not* the cheapest — which happens whenever
 * cross-merchant reputation escalates it — the panel has to say so. Showing costs that
 * contradict the verdict with no explanation reads as a bug, and it undermines the one
 * thing this interface is for.
 */

const ACTION_TONE: Record<MerchantAction, 'accept' | 'challenge' | 'hold'> = {
  ACCEPT: 'accept',
  STEP_UP: 'challenge',
  HOLD: 'hold',
};

const ACTION_LABEL: Record<MerchantAction, string> = {
  ACCEPT: 'ACCEPT',
  STEP_UP: 'CHALLENGE',
  HOLD: 'HOLD',
};

const ACTION_INSTRUCTION: Record<MerchantAction, string> = {
  ACCEPT: 'Fulfil the order',
  STEP_UP: '3-D Secure before capture',
  HOLD: 'Review before fulfilment',
};

const rupees = (v: number) => `₹${Math.round(v).toLocaleString('en-IN')}`;

/* -------------------------------------------------------------------------- */
/* Risk bar                                                                     */
/* -------------------------------------------------------------------------- */
/**
 * Probability against the decision threshold, on one axis.
 *
 * A lone percentage is close to meaningless here: the engine ships a cost-calibrated
 * threshold that can sit anywhere, so 55% is only alarming once you know the line is
 * at 26.8%. Putting both on the same track makes the relationship the primary fact.
 */
function RiskBar({
  probability,
  threshold,
  tone,
}: {
  probability: number;
  threshold?: number | null;
  tone: string;
}) {
  const reduced = useReducedMotion();
  const pct = Math.max(0, Math.min(1, probability));
  const counted = useCountUp(pct * 100);
  const line = typeof threshold === 'number' ? Math.max(0, Math.min(1, threshold)) : null;
  const over = line !== null && pct >= line;

  return (
    <section>
      <div className="flex items-baseline justify-between" style={{ marginBottom: 7 }}>
        <h3 className="nb-label">Fraud risk</h3>
        <span className="nb-mono nb-display" style={{ fontSize: 20, color: tone }}>
          {counted.toFixed(1)}%
        </span>
      </div>

      <div
        style={{
          position: 'relative',
          height: 26,
          background: 'var(--sunk)',
          border: 'var(--border)',
          borderRadius: 'var(--radius-sm)',
          overflow: 'hidden',
        }}
        role="img"
        aria-label={
          `Fraud risk ${(pct * 100).toFixed(1)} percent` +
          (line !== null
            ? `, ${over ? 'above' : 'below'} the ${(line * 100).toFixed(1)} percent decision threshold`
            : '')
        }
      >
        <motion.div
          initial={reduced ? false : { width: 0 }}
          animate={{ width: `${pct * 100}%` }}
          transition={reduced ? { duration: 0 } : SPRING}
          style={{ height: '100%', background: tone }}
        />
        {line !== null && (
          // The threshold is drawn over the fill so it stays visible on either side.
          <div
            style={{
              position: 'absolute',
              left: `${line * 100}%`,
              top: -2,
              bottom: -2,
              width: 3,
              background: 'var(--ink)',
            }}
            aria-hidden="true"
          />
        )}
      </div>

      {line !== null && (
        <div
          className="nb-mono flex justify-between"
          style={{ fontSize: 10.5, color: 'var(--faint)', marginTop: 4 }}
        >
          <span>0%</span>
          <span style={{ color: 'var(--ink)', fontWeight: 700 }}>
            holds at {(line * 100).toFixed(1)}%
          </span>
          <span>100%</span>
        </div>
      )}
    </section>
  );
}

/* -------------------------------------------------------------------------- */
/* Cost comparison                                                              */
/* -------------------------------------------------------------------------- */
/**
 * What each action would cost, as bars.
 *
 * The project's central claim is that the action is chosen by price rather than by a
 * threshold on a score. That claim is checkable here in one glance — or visibly not,
 * when something overrode it.
 */
function CostBars({
  costs,
  chosen,
}: {
  costs: Partial<Record<MerchantAction, number>>;
  chosen: MerchantAction;
}) {
  const reduced = useReducedMotion();
  const entries = (Object.entries(costs) as [MerchantAction, number][]).filter(
    ([, v]) => typeof v === 'number' && Number.isFinite(v),
  );
  if (entries.length === 0) return null;

  const max = Math.max(...entries.map(([, v]) => v), 1);
  const cheapest = entries.reduce((a, b) => (b[1] < a[1] ? b : a))[0];
  const ordered = [...entries].sort((a, b) => a[1] - b[1]);

  return (
    <section>
      <h3 className="nb-label" style={{ marginBottom: 7 }}>
        What each action would cost
      </h3>

      <div className="flex flex-col gap-1.5">
        {ordered.map(([action, cost], i) => {
          const isChosen = action === chosen;
          const isCheapest = action === cheapest;
          const tone = `var(--${ACTION_TONE[action]}-fill)`;

          return (
            <div key={action} className="flex items-center gap-2.5">
              <span
                className="nb-mono"
                style={{
                  fontSize: 10.5,
                  fontWeight: 700,
                  width: 74,
                  flexShrink: 0,
                  color: isChosen ? 'var(--ink)' : 'var(--muted)',
                }}
              >
                {ACTION_LABEL[action]}
              </span>

              <div
                style={{
                  position: 'relative',
                  flex: 1,
                  height: 20,
                  background: 'var(--sunk)',
                  border: isChosen ? 'var(--border)' : '1px solid var(--edge)',
                  borderRadius: 'var(--radius-sm)',
                  overflow: 'hidden',
                }}
              >
                <motion.div
                  initial={reduced ? false : { width: 0 }}
                  animate={{ width: `${Math.max(2, (cost / max) * 100)}%` }}
                  transition={reduced ? { duration: 0 } : { ...SPRING, delay: i * 0.06 }}
                  style={{ height: '100%', background: tone, opacity: isChosen ? 1 : 0.45 }}
                />
              </div>

              <span
                className="nb-mono"
                style={{
                  fontSize: 12,
                  width: 74,
                  textAlign: 'right',
                  flexShrink: 0,
                  fontWeight: isChosen ? 700 : 400,
                  color: isChosen ? 'var(--ink)' : 'var(--muted)',
                }}
              >
                {rupees(cost)}
              </span>

              <span style={{ width: 62, flexShrink: 0 }}>
                {isChosen && <Badge tone={ACTION_TONE[action]}>TAKEN</Badge>}
                {!isChosen && isCheapest && (
                  <span className="nb-label" style={{ color: 'var(--faint)' }}>
                    cheapest
                  </span>
                )}
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
}

/* -------------------------------------------------------------------------- */
/* Panel                                                                        */
/* -------------------------------------------------------------------------- */
export function EvaluationPanel({
  isLoading,
  results,
  threshold,
}: {
  isLoading: boolean;
  results: FraudDetectionResponse | null;
  threshold?: number | null;
}) {
  const costs = results?.action_costs ?? {};
  const entries = (Object.entries(costs) as [MerchantAction, number][]).filter(
    ([, v]) => typeof v === 'number',
  );
  const cheapest = entries.length
    ? entries.reduce((a, b) => (b[1] < a[1] ? b : a))[0]
    : null;
  const escalated =
    results !== null && cheapest !== null && cheapest !== results.action;

  return (
    <Panel
      title="Verdict"
      subtitle="What the engine decided, and what every other action would have cost"
    >
      <div aria-live="polite" className="flex flex-col gap-6">
        {isLoading && (
          <>
            <div className="nb-skeleton" style={{ height: 52, width: '62%' }} aria-hidden="true" />
            <div className="nb-skeleton" style={{ height: 58 }} aria-hidden="true" />
            <div className="nb-skeleton" style={{ height: 92 }} aria-hidden="true" />
            <p className="nb-label" role="status">
              Scoring…
            </p>
          </>
        )}

        {!isLoading && !results && (
          <div className="flex flex-col items-start gap-2" style={{ padding: '28px 0 36px' }}>
            <span style={{ color: 'var(--faint)' }}>
              <Icon name="activity" size={26} />
            </span>
            <p className="nb-display" style={{ fontSize: 17 }}>
              No payment scored yet
            </p>
            <p style={{ fontSize: 12.5, color: 'var(--muted)', maxWidth: '46ch' }}>
              Fill the form, or replay one of the scam signatures. The verdict, the risk
              against the threshold, and the cost of every alternative action all land here.
            </p>
          </div>
        )}

        {!isLoading && results && (
          <>
            {/* Verdict ---------------------------------------------------- */}
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
              <span
                className="nb-display"
                style={{
                  fontSize: 34,
                  lineHeight: 1,
                  padding: '8px 16px',
                  background: `var(--${ACTION_TONE[results.action]}-fill)`,
                  color: '#0b0b0b',
                  border: 'var(--border)',
                  borderRadius: 'var(--radius)',
                  boxShadow: 'var(--shadow-hard)',
                }}
              >
                {ACTION_LABEL[results.action]}
              </span>
              <div>
                <p className="nb-display" style={{ fontSize: 17 }}>
                  {ACTION_INSTRUCTION[results.action]}
                </p>
                <p className="nb-mono" style={{ fontSize: 11.5, color: 'var(--muted)' }}>
                  {results.status === 'BLOCKED' ? 'not settled' : 'settled'}
                </p>
              </div>
            </div>

            <RiskBar
              probability={results.fraud_probability}
              threshold={threshold}
              tone={`var(--${ACTION_TONE[results.action]}-fill)`}
            />

            <CostBars costs={costs} chosen={results.action} />

            {/* The panel would otherwise be showing a cheaper action it did not take,
                with no reason given — which reads as a defect rather than a policy. */}
            {escalated && (
              <Notice tone="challenge" icon="network">
                <strong style={{ fontWeight: 700 }}>Escalated past the cheapest action.</strong>{' '}
                {results.network_reasons?.length
                  ? results.network_reasons.join('; ')
                  : 'Cross-merchant evidence raised this beyond what the payment alone justifies.'}
              </Notice>
            )}

            {/* Metadata --------------------------------------------------- */}
            <div
              className="nb-mono flex flex-wrap items-center gap-x-3 gap-y-1"
              style={{
                fontSize: 10.5,
                color: 'var(--faint)',
                borderTop: '1px solid var(--edge)',
                paddingTop: 10,
              }}
            >
              <span
                style={{
                  color: results.execution_time_ms < 100 ? 'var(--accept)' : 'var(--challenge)',
                  fontWeight: 700,
                }}
              >
                {results.execution_time_ms} ms
              </span>
              <span aria-hidden="true">·</span>
              <span>{results.transaction_id}</span>
              {results.rung && results.rung !== 'full model' && (
                <>
                  <span aria-hidden="true">·</span>
                  <span style={{ color: 'var(--challenge)', fontWeight: 700 }}>
                    {results.rung}
                  </span>
                </>
              )}
              {results.decision_id && (
                <>
                  <span aria-hidden="true">·</span>
                  <span>{results.decision_id}</span>
                </>
              )}
            </div>
          </>
        )}
      </div>
    </Panel>
  );
}
