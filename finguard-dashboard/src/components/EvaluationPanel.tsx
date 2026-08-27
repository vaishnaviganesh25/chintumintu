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

const ACTION_SETTLEMENT: Record<MerchantAction, string> = {
  ACCEPT: 'settles now',
  STEP_UP: 'settles once the challenge clears',
  HOLD: 'not settled',
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

  // A model that prints "100.0%" is claiming a certainty it does not have — the figure
  // underneath is a rounded 0.9997, and a calibration-conscious reviewer will read the
  // rounding as a claim. Clamp the *displayed* number at both ends and say so with the
  // comparator; the raw probability still drives the bar and the decision.
  const pegged = pct >= 0.9995 ? 'high' : pct > 0 && pct < 0.0005 ? 'low' : null;
  const counted = useCountUp(pegged === 'high' ? 99.9 : pegged === 'low' ? 0.1 : pct * 100);
  const readout = `${pegged === 'high' ? '>' : pegged === 'low' ? '<' : ''}${counted.toFixed(1)}%`;

  const line = typeof threshold === 'number' ? Math.max(0, Math.min(1, threshold)) : null;
  const over = line !== null && pct >= line;

  return (
    <section>
      <div className="flex items-baseline justify-between" style={{ marginBottom: 7 }}>
        <h3 className="nb-label">Fraud risk</h3>
        <span className="nb-mono nb-display" style={{ fontSize: 20, color: tone }}>
          {readout}
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
          `Fraud risk ${readout}` +
          (line !== null
            ? `, ${over ? 'above' : 'below'} the ${(line * 100).toFixed(1)} percent calibrated cut-off`
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
        // In a space-between row this caption landed at the 50% mark while the notch it
        // describes was at 26.8% — a label pointing at a number that is not there. It is
        // now anchored to the notch, with a tick tying the two together.
        <div style={{ position: 'relative', height: 21, marginTop: 3 }}>
          <span
            style={{
              position: 'absolute',
              left: `${line * 100}%`,
              top: 0,
              width: 3,
              height: 5,
              marginLeft: -1,
              background: 'var(--ink)',
            }}
            aria-hidden="true"
          />
          <span
            className="nb-mono"
            style={{
              position: 'absolute',
              top: 7,
              left: `${line * 100}%`,
              // Near either end the label would overhang the track, so it pins to the
              // inside edge instead of centring.
              transform: `translateX(${line < 0.14 ? '0%' : line > 0.86 ? '-100%' : '-50%'})`,
              whiteSpace: 'nowrap',
              fontSize: 10.5,
              fontWeight: 700,
              color: 'var(--ink)',
            }}
          >
            calibrated cut-off {(line * 100).toFixed(1)}%
          </span>
          <span
            className="nb-mono"
            style={{ position: 'absolute', top: 7, left: 0, fontSize: 10.5, color: 'var(--faint)' }}
          >
            0%
          </span>
          <span
            className="nb-mono"
            style={{ position: 'absolute', top: 7, right: 0, fontSize: 10.5, color: 'var(--faint)' }}
          >
            100%
          </span>
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
 *
 * Length carries cost and nothing else. Action colour sits on a swatch and on the bar
 * that was actually taken, never on the others: a full-width bar in ACCEPT-green for
 * the single most expensive option was reading as an endorsement of it.
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
  const ordered = [...entries].sort((a, b) => a[1] - b[1]);
  const cheapest = ordered[0][0];
  const chosenCost = costs[chosen];

  // The punchline of the whole panel is one subtraction, so do it for the reader
  // rather than making them do it across two columns.
  const saving =
    typeof chosenCost === 'number' && chosen === cheapest && ordered.length > 1
      ? ordered[1][1] - chosenCost
      : null;
  const excess =
    typeof chosenCost === 'number' && chosen !== cheapest ? chosenCost - ordered[0][1] : null;

  return (
    <section>
      <h3 className="nb-label" style={{ marginBottom: 7 }}>
        What each action would cost
      </h3>

      <div className="flex flex-col gap-1.5" role="list">
        {ordered.map(([action, cost], i) => {
          const isChosen = action === chosen;
          const isCheapest = action === cheapest;

          return (
            <div key={action} className="flex items-center gap-2.5" role="listitem">
              {/* The action's colour lives on this swatch, not on the bar. Colour is
                  identity here; length is money. */}
              <span
                style={{
                  width: 10,
                  height: 10,
                  flexShrink: 0,
                  background: `var(--${ACTION_TONE[action]}-fill)`,
                  border: '1px solid var(--ink)',
                }}
                aria-hidden="true"
              />
              <span
                className="nb-mono"
                style={{
                  fontSize: 10.5,
                  fontWeight: 700,
                  width: 68,
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
                  style={{
                    height: '100%',
                    // Only the taken action is coloured. Painting every bar its action
                    // colour put a full-width *green* bar on ACCEPT whenever accepting
                    // was the most expensive option — long and green reads as "good",
                    // which is the exact opposite of what the number says.
                    background: isChosen
                      ? `var(--${ACTION_TONE[action]}-fill)`
                      : 'color-mix(in srgb, var(--ink) 22%, transparent)',
                  }}
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

      {(saving !== null || excess !== null) && (
        <p style={{ fontSize: 11.5, color: 'var(--muted)', marginTop: 9 }}>
          {saving !== null ? (
            <>
              <strong style={{ color: 'var(--ink)', fontWeight: 700 }}>
                {ACTION_LABEL[chosen]}
              </strong>{' '}
              is the cheapest of the three — {rupees(saving)} below the next best.
            </>
          ) : (
            <>
              Costs{' '}
              <strong style={{ color: 'var(--ink)', fontWeight: 700 }}>
                {rupees(excess as number)} more
              </strong>{' '}
              than {ACTION_LABEL[cheapest]}, which was the cheapest.
            </>
          )}
        </p>
      )}
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
  const reasons = results?.network_reasons ?? [];
  const outranked = results !== null && cheapest !== null && cheapest !== results.action;
  // Two separate triggers on purpose. `outranked` must be explained or the costs read as
  // a bug; `reasons` is evidence that fired and is worth showing even when the ordering
  // came out the same way regardless.
  const escalated = outranked || reasons.length > 0;

  // `status` is the legacy block/allow call at the calibrated cut-off; `action` is the
  // cost-chosen one. HOLD and ACCEPT are the only actions that map onto that binary,
  // so a STEP_UP is always a divergence from it.
  const divergent =
    results !== null &&
    (results.action === 'STEP_UP' ||
      (results.status === 'BLOCKED') !== (results.action === 'HOLD'));

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
                  {ACTION_SETTLEMENT[results.action]}
                </p>
              </div>
            </div>

            <RiskBar
              probability={results.fraud_probability}
              threshold={threshold}
              tone={`var(--${ACTION_TONE[results.action]}-fill)`}
            />

            {/* The cut-off and the cost comparison are two different policies over the
                same probability, and they do not always agree. That disagreement is the
                argument this project makes, so it is stated rather than left for the
                reader to infer from a notch. */}
            {typeof threshold === 'number' && divergent && (
              <p style={{ fontSize: 11.5, color: 'var(--muted)', marginTop: -8 }}>
                A single cut-off at {(threshold * 100).toFixed(1)}% would have{' '}
                <strong style={{ color: 'var(--ink)', fontWeight: 700 }}>
                  {results.status === 'BLOCKED' ? 'blocked' : 'allowed'}
                </strong>{' '}
                this payment. Pricing the three actions chose{' '}
                <strong style={{ color: 'var(--ink)', fontWeight: 700 }}>
                  {ACTION_LABEL[results.action]}
                </strong>
                .
              </p>
            )}

            <CostBars costs={costs} chosen={results.action} />

            {/* The panel would otherwise be showing a cheaper action it did not take,
                with no reason given — which reads as a defect rather than a policy. */}
            {escalated && (
              <Notice tone="challenge" icon="network">
                <strong style={{ fontWeight: 700 }}>
                  {outranked ? 'Escalated past the cheapest action.' : 'Cross-merchant evidence.'}
                </strong>{' '}
                {reasons.length
                  ? reasons.join('; ')
                  : 'Reputation raised this beyond what the payment alone justifies.'}
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
