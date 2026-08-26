import { useEffect, useState, type ReactNode } from 'react';
import { fetchModelCard, isAbortError } from '../services/opsApi';

/**
 * The model's own record, served straight from `model_config.json`.
 *
 * Read rather than re-derived, deliberately. A dashboard that recomputes its own
 * metrics is a second implementation that can disagree with the training run, and the
 * disagreement always surfaces in front of someone asking a hard question. What is on
 * this page is what the run actually produced.
 *
 * It leads with the ablations rather than the headline, because that is the honest
 * order: the headline is what the model scores on a synthetic dataset built to contain
 * exactly the patterns it detects, and the ablations are what is left when you take
 * away the features least likely to survive production.
 */

type Card = Record<string, any>;

const pct = (v: number) => `${(v * 100).toFixed(1)}%`;
const num = (v: number, dp = 4) => v.toFixed(dp);
const rupees = (v: number) => `₹${Math.round(v).toLocaleString('en-IN')}`;

function Section({ title, note, children }: { title: string; note?: string; children: ReactNode }) {
  return (
    <section className="fg-surface" style={{ padding: '18px 20px' }}>
      <h2 style={{ fontSize: 13, fontWeight: 600, marginBottom: note ? 2 : 12 }}>{title}</h2>
      {note && (
        <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 12, maxWidth: '72ch' }}>
          {note}
        </p>
      )}
      {children}
    </section>
  );
}

function Table({ head, rows }: { head: string[]; rows: (string | number)[][] }) {
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
        <thead>
          <tr>
            {head.map((h, i) => (
              <th
                key={h}
                className="fg-label"
                style={{
                  textAlign: i === 0 ? 'left' : 'right',
                  padding: '7px 10px',
                  background: 'var(--sunk)',
                  whiteSpace: 'nowrap',
                }}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, r) => (
            <tr key={r}>
              {row.map((cell, i) => (
                <td
                  key={i}
                  className={i === 0 ? undefined : 'fg-mono'}
                  style={{
                    textAlign: i === 0 ? 'left' : 'right',
                    padding: '7px 10px',
                    borderBottom: '1px solid var(--rule)',
                    color: i === 0 ? 'var(--ink)' : 'var(--muted)',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ModelCard() {
  const [card, setCard] = useState<Card | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchModelCard(controller.signal)
      .then(setCard)
      .catch((err) => {
        // A request we cancelled ourselves is not a failure to report.
        if (isAbortError(err)) return;
        setError(err instanceof Error ? err.message : 'Could not load the card.');
      });
    return () => controller.abort();
  }, []);

  if (error) {
    return (
      <p className="fg-surface px-4 py-3" role="alert" style={{ fontSize: 13, color: 'var(--hold)' }}>
        {error}
      </p>
    );
  }
  if (!card) {
    return <p style={{ fontSize: 13, color: 'var(--muted)' }}>Loading…</p>;
  }

  const prod = card.production_metrics?.test ?? {};
  const noAge = card.ablation_no_vpa_age;
  const noGraph = card.ablation_no_graph_features;
  const neither = card.ablation_no_age_no_graph;
  const econ = card.merchant_economics;
  const integrity = card.split_integrity;

  return (
    <div className="flex flex-col gap-5" style={{ maxWidth: 1000 }}>
      <Section
        title="What shipped"
        note={`${card.best_model}, selected on cross-validated PR-AUC and trained ${String(card.created_at).slice(0, 10)}. The threshold is calibrated on out-of-fold probabilities, never on the test split it is reported against.`}
      >
        <Table
          head={['', 'value']}
          rows={[
            ['Model', String(card.best_model)],
            ['Decision threshold', num(card.optimal_threshold)],
            ['Threshold policy', String(card.threshold_policy?.active_policy ?? '—')],
            ['Split', String(card.split?.strategy ?? '—')],
            ['Features', String(
              (card.features?.engineered_numeric?.length ?? 0) +
              (card.features?.engineered_binary?.length ?? 0) +
              (card.features?.engineered_categorical?.length ?? 0),
            )],
            ['Graph features', card.graph_features_enabled ? 'enabled' : 'disabled'],
          ]}
        />
      </Section>

      {neither && noAge && (
        <Section
          title="Ablations — what each block of features is worth"
          note="Read PR-AUC, not recall. Each row is re-calibrated on its own out-of-fold probabilities, so the operating points differ and the recall column is not comparable across rows. PR-AUC is threshold-free, which is why it is the column to compare."
        >
          <Table
            head={['feature set', 'PR-AUC', 'recall', 'precision']}
            rows={[
              ['Everything', num(prod.pr_auc ?? 0), num(prod.recall ?? 0, 2), num(prod.precision ?? 0, 2)],
              ['Without receiver VPA age', num(noAge.pr_auc), num(noAge.recall, 2), num(noAge.precision, 2)],
              ['Without graph features', num(noGraph.pr_auc), num(noGraph.recall, 2), num(noGraph.precision, 2)],
              ['Without either', num(neither.pr_auc), num(neither.recall, 2), num(neither.precision, 2)],
            ]}
          />
          <p style={{ fontSize: 12, color: 'var(--muted)', marginTop: 12, maxWidth: '72ch' }}>
            Account age is an attribute of the receiving account, so a fraudster defeats
            it by ageing a mule for three weeks. Fan-in is a property of the ring&apos;s
            behaviour — collecting from several victims in minutes is the thing the scam
            has to do to be the scam. A ring cannot age its way out of it.
          </p>
        </Section>
      )}

      {integrity && (
        <Section
          title="Split integrity"
          note="A stratified random split cuts through scam incidents — the ₹1 probe lands in train while its drain lands in test. Grouping on the incident removes that, and cost real headline performance in doing so."
        >
          <Table
            head={['', 'value']}
            rows={[
              ['Test fraud sharing a receiver with train fraud',
                `${integrity.receiver_seen_in_train_fraud} / ${integrity.test_fraud_rows}`],
              ['Bleed rate', pct(integrity.bleed_rate)],
              ['Recall on receivers never seen in training',
                integrity.recall_cold === null ? '—' : pct(integrity.recall_cold)],
            ]}
          />
        </Section>
      )}

      {econ && (
        <Section
          title="Merchant economics"
          note="A flat false-positive cost is the wrong shape for a merchant: declining a good customer costs the margin on that order plus winning them back, so it scales with basket size. And a gateway can challenge a payment, which a bank cannot."
        >
          <Table
            head={['policy', 'total cost', 'per txn', 'held', 'challenged', 'fraud through']}
            rows={[
              [
                'Block / allow at threshold',
                rupees(econ.binary_policy_at_threshold.total_cost_inr),
                `₹${econ.binary_policy_at_threshold.cost_per_txn_inr.toFixed(2)}`,
                econ.binary_policy_at_threshold.held,
                '—',
                econ.binary_policy_at_threshold.fraud_accepted,
              ],
              [
                'Accept / step-up / hold',
                rupees(econ.three_action_policy.total_cost_inr),
                `₹${econ.three_action_policy.cost_per_txn_inr.toFixed(2)}`,
                econ.three_action_policy.held,
                econ.three_action_policy.stepped_up,
                econ.three_action_policy.fraud_accepted,
              ],
            ]}
          />
          <p style={{ fontSize: 12, color: 'var(--muted)', marginTop: 12, maxWidth: '72ch' }}>
            Challenges are capped at {pct(econ.three_action_policy.step_up_budget)} of payments
            and allocated by benefit. Unconstrained, row-by-row cost minimisation challenged
            94% of legitimate traffic — arithmetically optimal, and it would destroy
            conversion. Dispute ratio {pct(econ.three_action_policy.dispute_ratio)} against a{' '}
            {pct(econ.three_action_policy.dispute_ceiling)} network ceiling; at this fraud
            prevalence that covenant is slack by construction, and begins to bind above{' '}
            {pct(econ.covenant_binds_above_prevalence)}.
          </p>
        </Section>
      )}

      <Section title="Environment" note="Recorded at training time, so a decision stays reproducible.">
        <Table
          head={['', 'version']}
          rows={Object.entries(card.environment ?? {}).map(([k, v]) => [k, String(v)])}
        />
      </Section>
    </div>
  );
}
