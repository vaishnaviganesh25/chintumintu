import { useCallback, useEffect, useState } from 'react';
import { SHAPChart } from './SHAPChart';
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
  raiseDispute,
  recordDisposition,
} from '../services/opsApi';

/**
 * The fraud desk: the alert queue, one case in full, and what a reviewer can do with it.
 *
 * The simulator answers "what would the engine say about this payment". This answers
 * the question an operations team actually has — "what is waiting for me, and what do
 * I do about it" — and it is the only surface where the ledger, the dispositions and
 * the chargeback responder are visible at all.
 */

const REFRESH_MS = 10_000;

const rupees = (value: number) =>
  `₹${value.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;

const ACTION_STYLE: Record<string, string> = {
  HOLD: 'text-[var(--hold)] border-[var(--hold)] bg-[var(--hold-soft)]',
  STEP_UP: 'text-[var(--challenge)] border-[var(--challenge)] bg-[var(--challenge-soft)]',
  ACCEPT: 'text-[var(--accept)] border-[var(--accept)] bg-[var(--accept-soft)]',
};

const DISPOSITION_STYLE: Record<string, string> = {
  confirmed_fraud: 'text-[var(--hold)]',
  false_positive: 'text-[var(--accept)]',
  unclear: 'text-[var(--muted)]',
};

function StatTile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="bg-[var(--surface)] border border-[var(--rule)] rounded-lg px-4 py-3">
      <dt className="text-[11px] uppercase tracking-wider text-[var(--faint)]">{label}</dt>
      <dd className="text-xl font-semibold text-[var(--ink)] tabular-nums mt-0.5">{value}</dd>
      {hint && <p className="text-[11px] text-[var(--faint)] mt-0.5">{hint}</p>}
    </div>
  );
}

function StatsStrip({ stats }: { stats: OperatingStats | null }) {
  if (!stats) {
    return (
      <p className="text-sm text-[var(--faint)]">
        Operating stats unavailable — the decision ledger is not reachable.
      </p>
    );
  }

  return (
    <dl className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
      <StatTile label="Scored" value={stats.decisions_recorded.toLocaleString('en-IN')} />
      <StatTile label="Held" value={stats.held.toLocaleString('en-IN')} />
      <StatTile label="Challenged" value={stats.stepped_up.toLocaleString('en-IN')} />
      <StatTile label="Value held" value={rupees(stats.value_blocked_inr)} />
      <StatTile
        label="Reviewed precision"
        // Null is not zero. Nobody having judged anything yet is a different
        // statement from the engine being wrong every time.
        value={
          stats.precision_reviewed === null
            ? '—'
            : `${(stats.precision_reviewed * 100).toFixed(0)}%`
        }
        hint={`over ${stats.reviewed} reviewed`}
      />
      <StatTile
        label="Disputes"
        value={stats.disputes_raised.toLocaleString('en-IN')}
        hint={
          stats.packets_drafted_degraded > 0
            ? `${stats.packets_drafted_degraded} drafted without a model`
            : undefined
        }
      />
    </dl>
  );
}

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

  // A fallback rung writes -1 rather than a made-up probability, so the UI has to
  // say "no score" instead of rendering a gauge at -100%.
  const scored = decision.fraud_probability >= 0;

  const shapFeatures = Object.entries(decision.shap_concepts ?? {})
    .map(([feature, importance]) => ({ feature, importance }))
    .sort((a, b) => Math.abs(b.importance) - Math.abs(a.importance));

  const disposition = async (outcome: DisputeOutcome) => {
    setBusy(outcome);
    setError(null);
    try {
      await recordDisposition(decision.decision_id, outcome);
      onDispositioned();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not record that.');
    } finally {
      setBusy(null);
    }
  };

  const startDispute = async () => {
    setBusy('dispute');
    setError(null);
    try {
      setDispute(
        await raiseDispute(
          decision.decision_id,
          'Cardholder reports an unauthorised transaction',
        ),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not draft a packet.');
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-5">
      <div>
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="text-lg font-semibold text-[var(--ink)]">{rupees(decision.amount)}</span>
          <span
            className={`text-[11px] font-bold px-2 py-0.5 rounded border ${
              ACTION_STYLE[decision.decision] ?? ACTION_STYLE.HOLD
            }`}
          >
            {decision.decision}
          </span>
          <span className="text-xs text-[var(--faint)] font-mono">{decision.decision_id}</span>
        </div>
        <p className="text-sm text-[var(--muted)] mt-1 break-all">
          {decision.sender_vpa} → {decision.receiver_vpa}
        </p>
        <p className="text-xs text-[var(--faint)] mt-1">
          {decision.txn_timestamp ?? decision.scored_at} · receiver{' '}
          {decision.receiver_vpa_age_days ?? '?'} days old · {decision.latency_ms} ms
        </p>
      </div>

      <dl className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
        <div>
          <dt className="text-[11px] uppercase tracking-wider text-[var(--faint)]">Risk</dt>
          <dd className="text-[var(--ink)] tabular-nums">
            {scored ? decision.fraud_probability.toFixed(4) : 'no score'}
          </dd>
        </div>
        <div>
          <dt className="text-[11px] uppercase tracking-wider text-[var(--faint)]">Threshold</dt>
          <dd className="text-[var(--ink)] tabular-nums">{decision.threshold.toFixed(4)}</dd>
        </div>
        <div>
          <dt className="text-[11px] uppercase tracking-wider text-[var(--faint)]">Model</dt>
          <dd className="text-[var(--ink)] break-all">{decision.model_name}</dd>
        </div>
        <div>
          <dt className="text-[11px] uppercase tracking-wider text-[var(--faint)]">Policy</dt>
          <dd className="text-[var(--ink)]">{decision.threshold_policy ?? '—'}</dd>
        </div>
      </dl>

      {!scored && (
        <p className="text-xs text-[var(--challenge)] border rounded px-3 py-2">
          Scored by a fallback rung — the model was unavailable, so there is no
          probability and no SHAP breakdown for this decision.
        </p>
      )}

      {decision.reasons?.length > 0 && (
        <div>
          <h4 className="text-[11px] uppercase tracking-wider text-[var(--faint)] mb-1">
            Recorded at decision time
          </h4>
          <ul className="text-sm text-[var(--ink)] space-y-0.5">
            {decision.reasons.map((reason) => (
              <li key={reason}>+ {reason}</li>
            ))}
          </ul>
        </div>
      )}

      {shapFeatures.length > 0 && (
        <div>
          <h4 className="text-[11px] uppercase tracking-wider text-[var(--faint)] mb-1">
            Evidence replayed from the ledger
          </h4>
          <p className="text-[11px] text-[var(--faint)] mb-2">
            The contributions stored when the decision was made — not recomputed against
            today&apos;s model.
          </p>
          <SHAPChart features={shapFeatures} />
        </div>
      )}

      {/* Reviewer actions ------------------------------------------------- */}
      <div className="border-t border-[var(--rule)] pt-4">
        <h4 className="text-[11px] uppercase tracking-wider text-[var(--faint)] mb-2">
          Record an outcome
        </h4>
        <div className="flex flex-wrap gap-2">
          {(['confirmed_fraud', 'false_positive', 'unclear'] as DisputeOutcome[]).map((outcome) => (
            <button
              key={outcome}
              type="button"
              onClick={() => void disposition(outcome)}
              disabled={busy !== null}
              className="px-3 py-1.5 text-sm rounded-md border border-[var(--rule-strong)] bg-[var(--sunk)] text-[var(--ink)] hover:bg-[var(--sunk)] disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-[var(--accent)]"
            >
              {busy === outcome ? 'Saving…' : outcome.replace('_', ' ')}
            </button>
          ))}
          <button
            type="button"
            onClick={() => void startDispute()}
            disabled={busy !== null}
            className="px-3 py-1.5 text-sm rounded-md border border-[var(--accent)] bg-[var(--accent-soft)] text-[var(--accent)] hover:bg-[var(--accent-soft)] disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-[var(--accent)]"
          >
            {busy === 'dispute' ? 'Drafting…' : 'Raise chargeback'}
          </button>
        </div>

        {decision.dispositions && decision.dispositions.length > 0 && (
          <ul className="mt-3 text-xs text-[var(--muted)] space-y-0.5">
            {decision.dispositions.map((d) => (
              <li key={d.disposition_id}>
                <span className={DISPOSITION_STYLE[d.outcome] ?? ''}>{d.outcome}</span>{' '}
                by {d.reviewer ?? 'unknown'} · {d.recorded_at.slice(0, 19).replace('T', ' ')}
              </li>
            ))}
          </ul>
        )}

        {error && (
          <p className="text-sm text-[var(--hold)] mt-2" role="alert">
            {error}
          </p>
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
    <div className="border-t border-[var(--rule)] pt-4 space-y-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h4 className="text-sm font-semibold text-[var(--ink)]">Representment packet</h4>
        <span
          className={`text-[11px] font-bold px-2 py-0.5 rounded border ${
            conceding
              ? 'text-[var(--ink)] border-[var(--rule-strong)] bg-[var(--surface)]'
              : 'text-[var(--accent)] border-[var(--accent)] bg-[var(--accent-soft)]'
          }`}
        >
          {conceding ? 'ACCEPT LIABILITY' : 'REPRESENT'}
        </span>
        <span className="text-xs text-[var(--faint)] tabular-nums">
          confidence {(packet.confidence * 100).toFixed(0)}%
        </span>
      </div>

      <p className="text-xs text-[var(--faint)]">
        {dispute.reason_code_label ?? packet.reason_code} · drafted by{' '}
        <span className="font-mono">{packet.generated_by}</span>
      </p>

      {packet.degraded && (
        <p className="text-xs text-[var(--challenge)] border rounded px-3 py-2">
          No language model was reachable, so this is a template draft assembled from
          the same ledger evidence. It needs a human pass before filing — but a dispute
          has a deadline, so it exists rather than not.
        </p>
      )}

      <p className="text-sm text-[var(--ink)]">{packet.summary}</p>

      {packet.compelling_evidence.length > 0 && (
        <div>
          <h5 className="text-[11px] uppercase tracking-wider text-[var(--faint)] mb-1">
            Compelling evidence
          </h5>
          <ul className="text-sm text-[var(--ink)] space-y-1">
            {packet.compelling_evidence.map((item) => (
              <li key={item.item}>
                <span className="text-[var(--ink)]">{item.item}:</span> {item.detail}{' '}
                <span className="text-[var(--faint)] text-xs">[{item.source}]</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div>
        <h5 className="text-[11px] uppercase tracking-wider text-[var(--faint)] mb-1">Argument</h5>
        <pre className="text-xs text-[var(--ink)] whitespace-pre-wrap font-sans bg-[var(--sunk)] border border-[var(--rule)] rounded p-3 overflow-x-auto">
          {packet.argument}
        </pre>
      </div>

      {packet.issuer_rebuttals.length > 0 && (
        <div>
          <h5 className="text-[11px] uppercase tracking-wider text-[var(--faint)] mb-1">
            Expect the issuer to argue
          </h5>
          <ul className="text-sm text-[var(--muted)] space-y-0.5">
            {packet.issuer_rebuttals.map((rebuttal) => (
              <li key={rebuttal}>− {rebuttal}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

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
      if (signal?.aborted) return;
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
    // The list entry is a summary; the detail view needs the full record with its
    // dispositions, so it is fetched rather than reused.
    setSelected(row);
    try {
      setSelected(await fetchDecision(row.decision_id));
    } catch {
      /* keep the summary — a failed detail fetch should not blank the panel */
    }
  };

  return (
    <div className="space-y-6">
      <StatsStrip stats={stats} />

      {error && (
        <div className="border text-[var(--hold)] px-4 py-3 rounded-lg" role="alert">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="fg-surface p-5">
          <h2 className="text-[13px] font-semibold mb-1">Alert queue</h2>
          <p className="text-sm text-[var(--muted)] mb-4">
            Payments held or challenged, newest first. Accepted payments are recorded too
            and are not shown here.
          </p>

          {loaded && queue.length === 0 && !error && (
            <p className="text-sm text-[var(--faint)] py-8 text-center">
              Nothing waiting. Score a risky payment in the simulator and it will appear here.
            </p>
          )}

          <ul className="divide-y divide-[var(--rule)] max-h-[28rem] overflow-y-auto -mx-2">
            {queue.map((row) => (
              <li key={row.decision_id}>
                <button
                  type="button"
                  onClick={() => void open(row)}
                  className={`w-full text-left px-2 py-3 hover:bg-[var(--sunk)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)] rounded ${
                    selected?.decision_id === row.decision_id ? 'bg-[var(--sunk)]' : ''
                  }`}
                >
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="text-[var(--ink)] font-medium tabular-nums">
                      {rupees(row.amount)}
                    </span>
                    <span
                      className={`text-[10px] font-bold px-1.5 py-0.5 rounded border ${
                        ACTION_STYLE[row.decision] ?? ACTION_STYLE.HOLD
                      }`}
                    >
                      {row.decision}
                    </span>
                  </div>
                  <p className="text-xs text-[var(--muted)] truncate mt-0.5">
                    {row.sender_vpa} → {row.receiver_vpa}
                  </p>
                  <p className="text-[11px] text-[var(--faint)] mt-0.5">
                    {row.fraud_probability >= 0
                      ? `risk ${row.fraud_probability.toFixed(3)}`
                      : 'no score (fallback)'}
                    {row.latest_disposition && (
                      <>
                        {' · '}
                        <span className={DISPOSITION_STYLE[row.latest_disposition] ?? ''}>
                          {row.latest_disposition.replace('_', ' ')}
                        </span>
                      </>
                    )}
                  </p>
                </button>
              </li>
            ))}
          </ul>
        </div>

        <div className="fg-surface p-5">
          <h2 className="text-xl font-semibold text-[var(--accent)] mb-4">Case file</h2>
          {selected ? (
            <CaseDetail decision={selected} onDispositioned={() => void refresh()} />
          ) : (
            <p className="text-sm text-[var(--faint)] py-12 text-center">
              Select an alert to replay its evidence, record an outcome, or draft a
              chargeback response.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
