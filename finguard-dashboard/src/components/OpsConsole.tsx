import { useCallback, useEffect, useState } from 'react';
import { SHAPChart } from './SHAPChart';
import {
  Badge,
  Button,
  Drawer,
  Notice,
  Panel,
  StaggerItem,
  StaggerList,
  Stat,
} from './ui';
import type {
  DecisionRecord,
  DisputeOutcome,
  DisputeRecord,
  OperatingStats,
} from '../types';
import {
  fetchDecision,
  fetchQueue,
  fetchStats,
  isAbortError,
  raiseDispute,
  recordDisposition,
} from '../services/opsApi';

/**
 * The fraud desk: the alert queue, one case in full, and what a reviewer can do.
 *
 * The simulator answers "what would the engine say about this payment". This answers
 * the question an operations team actually has — what is waiting for me, and what do I
 * do about it — and it is the only surface where the ledger, the dispositions and the
 * chargeback responder are visible at all.
 *
 * The case file is a glass drawer rather than a second column. It is the one place in
 * this interface where depth carries meaning: the queue stays legible behind the case
 * pulled out of it, so you never lose your place in the list.
 */

const REFRESH_MS = 10_000;

const rupees = (value: number) =>
  `₹${value.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;

const ACTION_TONE: Record<string, 'accept' | 'challenge' | 'hold'> = {
  ACCEPT: 'accept',
  STEP_UP: 'challenge',
  HOLD: 'hold',
};

const DISPOSITION_COLOUR: Record<string, string> = {
  confirmed_fraud: 'var(--hold)',
  false_positive: 'var(--accept)',
  unclear: 'var(--muted)',
};

/* -------------------------------------------------------------------------- */
/* Stats                                                                       */
/* -------------------------------------------------------------------------- */
function StatsStrip({ stats, loading }: { stats: OperatingStats | null; loading: boolean }) {
  if (loading) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        {Array.from({ length: 6 }, (_, i) => (
          <div key={i} className="nb-skeleton" style={{ height: 84 }} aria-hidden="true" />
        ))}
      </div>
    );
  }

  if (!stats) {
    return (
      <Notice tone="challenge" icon="alert">
        Operating stats unavailable — the decision ledger is not reachable. Scoring still
        works; history does not.
      </Notice>
    );
  }

  const tiles = [
    { label: 'Scored', value: stats.decisions_recorded },
    { label: 'Held', value: stats.held, tone: 'hold' as const },
    { label: 'Challenged', value: stats.stepped_up, tone: 'challenge' as const },
    { label: 'Value held', value: stats.value_blocked_inr, format: rupees },
    {
      label: 'Reviewed precision',
      // Null is not zero. Nobody having judged anything yet is a different statement
      // from the engine being wrong every time.
      value: stats.precision_reviewed === null ? '—' : stats.precision_reviewed * 100,
      format: (n: number) => `${Math.round(n)}%`,
      hint: `over ${stats.reviewed} reviewed`,
    },
    {
      label: 'Disputes',
      value: stats.disputes_raised,
      hint:
        stats.packets_drafted_degraded > 0
          ? `${stats.packets_drafted_degraded} without a model`
          : undefined,
    },
  ];

  return (
    <StaggerList className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
      {tiles.map((tile) => (
        <StaggerItem key={tile.label}>
          <Stat {...tile} />
        </StaggerItem>
      ))}
    </StaggerList>
  );
}

/* -------------------------------------------------------------------------- */
/* Case file                                                                   */
/* -------------------------------------------------------------------------- */
function CaseDetail({
  decision,
  onDispositioned,
}: {
  decision: DecisionRecord;
  onDispositioned: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [dispute, setDispute] = useState<DisputeRecord | null>(null);
  const [error, setError] = useState<string | null>(null);

  // A fallback rung writes -1 rather than a made-up probability, so the UI has to say
  // "no score" instead of rendering a gauge at minus one hundred percent.
  const scored = decision.fraud_probability >= 0;

  const shapFeatures = Object.entries(decision.shap_concepts ?? {})
    .map(([feature, importance]) => ({ feature, importance }))
    .sort((a, b) => Math.abs(b.importance) - Math.abs(a.importance));

  const act = async (label: string, run: () => Promise<unknown>) => {
    setBusy(label);
    setError(null);
    try {
      await run();
    } catch (err) {
      if (!isAbortError(err)) {
        setError(err instanceof Error ? err.message : 'That did not work.');
      }
    } finally {
      setBusy(null);
    }
  };

  const facts: [string, string][] = [
    ['Risk', scored ? decision.fraud_probability.toFixed(4) : 'no score'],
    ['Threshold', decision.threshold.toFixed(4)],
    ['Model', decision.model_name],
    ['Policy', decision.threshold_policy ?? '—'],
    ['Receiver age', `${decision.receiver_vpa_age_days ?? '?'} days`],
    ['Latency', `${decision.latency_ms} ms`],
  ];

  return (
    <div className="flex flex-col gap-5">
      <div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <span className="nb-display" style={{ fontSize: 26 }}>
            {rupees(decision.amount)}
          </span>
          <Badge tone={ACTION_TONE[decision.decision] ?? 'hold'}>{decision.decision}</Badge>
        </div>
        <p className="nb-mono" style={{ fontSize: 12, color: 'var(--muted)', marginTop: 6 }}>
          {decision.sender_vpa} → {decision.receiver_vpa}
        </p>
        <p className="nb-mono" style={{ fontSize: 11, color: 'var(--faint)', marginTop: 2 }}>
          {decision.decision_id}
        </p>
      </div>

      <dl className="grid grid-cols-2 gap-2.5">
        {facts.map(([label, value]) => (
          <div key={label} className="nb-panel-flat" style={{ padding: '9px 11px' }}>
            <dt className="nb-label">{label}</dt>
            <dd className="nb-mono truncate" style={{ fontSize: 13, marginTop: 2 }}>
              {value}
            </dd>
          </div>
        ))}
      </dl>

      {!scored && (
        <Notice tone="challenge" icon="alert">
          Scored by a fallback rung — the model was unavailable, so there is no
          probability and no SHAP breakdown for this decision.
        </Notice>
      )}

      {decision.reasons?.length > 0 && (
        <div>
          <h3 className="nb-label" style={{ marginBottom: 6 }}>
            Recorded at decision time
          </h3>
          <ul className="flex flex-col gap-1">
            {decision.reasons.map((reason) => (
              <li key={reason} style={{ fontSize: 12.5 }}>
                <span style={{ color: 'var(--hold)', fontWeight: 700 }}>+</span> {reason}
              </li>
            ))}
          </ul>
        </div>
      )}

      {shapFeatures.length > 0 && (
        <div>
          <h3 className="nb-label" style={{ marginBottom: 2 }}>
            Evidence replayed from the ledger
          </h3>
          <p style={{ fontSize: 11.5, color: 'var(--muted)', marginBottom: 8 }}>
            The contributions stored when the decision was made — not recomputed against
            today&apos;s model.
          </p>
          <SHAPChart features={shapFeatures} />
        </div>
      )}

      <div style={{ borderTop: 'var(--border)', paddingTop: 16 }}>
        <h3 className="nb-label" style={{ marginBottom: 8 }}>
          Record an outcome
        </h3>
        <div className="flex flex-wrap gap-2">
          {(['confirmed_fraud', 'false_positive', 'unclear'] as DisputeOutcome[]).map((outcome) => (
            <Button
              key={outcome}
              disabled={busy !== null}
              onClick={() =>
                void act(outcome, async () => {
                  await recordDisposition(decision.decision_id, outcome);
                  onDispositioned();
                })
              }
            >
              {busy === outcome ? 'Saving…' : outcome.replace(/_/g, ' ')}
            </Button>
          ))}
          <Button
            variant="primary"
            icon="file-text"
            disabled={busy !== null}
            onClick={() =>
              void act('dispute', async () => {
                setDispute(
                  await raiseDispute(
                    decision.decision_id,
                    'Cardholder reports they did not authorise this transaction',
                  ),
                );
              })
            }
          >
            {busy === 'dispute' ? 'Drafting…' : 'Raise chargeback'}
          </Button>
        </div>

        {decision.dispositions && decision.dispositions.length > 0 && (
          <ul className="flex flex-col gap-1" style={{ marginTop: 12 }}>
            {decision.dispositions.map((d) => (
              <li key={d.disposition_id} className="nb-mono" style={{ fontSize: 11 }}>
                <span style={{ color: DISPOSITION_COLOUR[d.outcome], fontWeight: 700 }}>
                  {d.outcome.replace(/_/g, ' ')}
                </span>{' '}
                <span style={{ color: 'var(--faint)' }}>
                  by {d.reviewer ?? 'unknown'} · {d.recorded_at.slice(0, 19).replace('T', ' ')}
                </span>
              </li>
            ))}
          </ul>
        )}

        {error && (
          <div style={{ marginTop: 10 }}>
            <Notice tone="hold" icon="alert">
              {error}
            </Notice>
          </div>
        )}
      </div>

      {dispute && <PacketView dispute={dispute} />}
    </div>
  );
}

function PacketView({ dispute }: { dispute: DisputeRecord }) {
  const packet = dispute.packet;
  const conceding = packet.recommendation === 'accept_liability';

  return (
    <div style={{ borderTop: 'var(--border)', paddingTop: 16 }} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2.5">
        <h3 className="nb-display" style={{ fontSize: 15 }}>
          Representment packet
        </h3>
        <Badge tone={conceding ? 'neutral' : 'accent'}>
          {conceding ? 'ACCEPT LIABILITY' : 'REPRESENT'}
        </Badge>
        <span className="nb-mono" style={{ fontSize: 11, color: 'var(--muted)' }}>
          confidence {(packet.confidence * 100).toFixed(0)}%
        </span>
      </div>

      <p className="nb-mono" style={{ fontSize: 11, color: 'var(--faint)' }}>
        {dispute.reason_code_label ?? packet.reason_code} · drafted by {packet.generated_by}
      </p>

      {packet.degraded && (
        <Notice tone="challenge" icon="alert">
          No language model was reachable, so this is a template draft assembled from the
          same ledger evidence. It needs a human pass before filing — but a dispute has a
          deadline, so it exists rather than not.
        </Notice>
      )}

      <p style={{ fontSize: 12.5 }}>{packet.summary}</p>

      {packet.compelling_evidence.length > 0 && (
        <div>
          <h4 className="nb-label" style={{ marginBottom: 5 }}>
            Compelling evidence
          </h4>
          <ul className="flex flex-col gap-1.5">
            {packet.compelling_evidence.map((item) => (
              <li key={item.item} style={{ fontSize: 12 }}>
                <span style={{ fontWeight: 600 }}>{item.item}:</span> {item.detail}{' '}
                <span className="nb-mono" style={{ color: 'var(--faint)', fontSize: 10.5 }}>
                  [{item.source}]
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div>
        <h4 className="nb-label" style={{ marginBottom: 5 }}>
          Argument
        </h4>
        <pre
          className="nb-panel-flat"
          style={{
            fontSize: 11.5,
            whiteSpace: 'pre-wrap',
            fontFamily: 'var(--font-sans)',
            padding: 12,
            background: 'var(--sunk)',
            overflowX: 'auto',
          }}
        >
          {packet.argument}
        </pre>
      </div>

      {packet.issuer_rebuttals.length > 0 && (
        <div>
          <h4 className="nb-label" style={{ marginBottom: 5 }}>
            Expect the issuer to argue
          </h4>
          <ul className="flex flex-col gap-1">
            {packet.issuer_rebuttals.map((rebuttal) => (
              <li key={rebuttal} style={{ fontSize: 12, color: 'var(--muted)' }}>
                − {rebuttal}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Console                                                                     */
/* -------------------------------------------------------------------------- */
export function OpsConsole() {
  const [queue, setQueue] = useState<DecisionRecord[]>([]);
  const [stats, setStats] = useState<OperatingStats | null>(null);
  const [selected, setSelected] = useState<DecisionRecord | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    try {
      const [rows, summary] = await Promise.all([fetchQueue(25, signal), fetchStats(signal)]);
      if (signal?.aborted) return;
      setQueue(rows);
      setStats(summary);
      setError(null);
    } catch (err) {
      if (signal?.aborted || isAbortError(err)) return;
      setError(err instanceof Error ? err.message : 'Could not load the queue.');
    } finally {
      if (!signal?.aborted) setLoaded(true);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    const timer = setInterval(() => void refresh(controller.signal), REFRESH_MS);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, [refresh]);

  const open = async (row: DecisionRecord) => {
    // The list entry is a summary; the drawer needs the full record with its
    // dispositions, so it is fetched rather than reused.
    setSelected(row);
    try {
      setSelected(await fetchDecision(row.decision_id));
    } catch {
      /* keep the summary — a failed detail fetch should not blank the drawer */
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <StatsStrip stats={stats} loading={!loaded} />

      {error && (
        <Notice tone="hold" icon="alert">
          {error}
        </Notice>
      )}

      <Panel
        title="Alert queue"
        subtitle="Payments held or challenged, newest first. Accepted payments are recorded too and are not shown here."
        padded={false}
      >
        {!loaded && (
          <div className="flex flex-col gap-2" style={{ padding: 18 }}>
            {Array.from({ length: 5 }, (_, i) => (
              <div key={i} className="nb-skeleton" style={{ height: 58 }} aria-hidden="true" />
            ))}
          </div>
        )}

        {loaded && queue.length === 0 && !error && (
          <p
            style={{
              fontSize: 13,
              color: 'var(--muted)',
              textAlign: 'center',
              padding: '48px 18px',
            }}
          >
            Nothing waiting. Score a risky payment in the simulator and it will appear here.
          </p>
        )}

        {loaded && queue.length > 0 && (
          <StaggerList>
            {queue.map((row) => (
              <StaggerItem key={row.decision_id}>
                <button
                  type="button"
                  onClick={() => void open(row)}
                  className="w-full text-left"
                  style={{
                    display: 'block',
                    padding: '12px 18px',
                    background: 'transparent',
                    border: 'none',
                    // A hairline, not a 2px ink border. Twenty-five rows of full
                    // brutalist borders cannot be scanned, and scanning is the job.
                    borderBottom: '1px solid var(--edge)',
                    cursor: 'pointer',
                    transition: 'background-color var(--dur-fast)',
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = 'var(--sunk)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = 'transparent';
                  }}
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="nb-mono" style={{ fontSize: 15, fontWeight: 700 }}>
                      {rupees(row.amount)}
                    </span>
                    <Badge tone={ACTION_TONE[row.decision] ?? 'hold'}>{row.decision}</Badge>
                  </div>
                  <p
                    className="nb-mono truncate"
                    style={{ fontSize: 11.5, color: 'var(--muted)', marginTop: 3 }}
                  >
                    {row.sender_vpa} → {row.receiver_vpa}
                  </p>
                  <p
                    className="nb-mono"
                    style={{ fontSize: 11, color: 'var(--faint)', marginTop: 2 }}
                  >
                    {row.fraud_probability >= 0
                      ? `risk ${row.fraud_probability.toFixed(3)}`
                      : 'no score (fallback)'}
                    {row.latest_disposition && (
                      <>
                        {' · '}
                        <span
                          style={{
                            color: DISPOSITION_COLOUR[row.latest_disposition],
                            fontWeight: 700,
                          }}
                        >
                          {row.latest_disposition.replace(/_/g, ' ')}
                        </span>
                      </>
                    )}
                  </p>
                </button>
              </StaggerItem>
            ))}
          </StaggerList>
        )}
      </Panel>

      <Drawer open={selected !== null} onClose={() => setSelected(null)} title="Case file">
        {selected && <CaseDetail decision={selected} onDispositioned={() => void refresh()} />}
      </Drawer>
    </div>
  );
}
