import { SHAPChart } from './SHAPChart';
import { Icon } from './Icon';
import { Panel } from './ui';
import type { SHAPFeature } from '../types';

/**
 * Where the numbers in this panel come from.
 *
 * An explanation panel that cannot say what produced its numbers is asking to be taken
 * on trust, which is the opposite of the point. Both references were checked against
 * the published record rather than written from memory; the second is cited by its
 * journal title, with the link pointing at the freely readable preprint, which carries
 * a slightly different title.
 */
const SOURCES = [
  {
    cite: 'Lundberg & Lee (2017). A Unified Approach to Interpreting Model Predictions.',
    where: 'Advances in Neural Information Processing Systems 30',
    href: 'https://arxiv.org/abs/1705.07874',
    note: 'The additivity and consistency guarantees the breakdown above relies on.',
  },
  {
    cite:
      'Lundberg, Erion, Chen et al. (2020). From local explanations to global ' +
      'understanding with explainable AI for trees.',
    where: 'Nature Machine Intelligence 2, 56–67',
    href: 'https://arxiv.org/abs/1905.04610',
    note: 'TreeSHAP: exact Shapley values for tree ensembles in polynomial time.',
  },
] as const;

function Method() {
  return (
    <footer
      style={{ marginTop: 18, paddingTop: 12, borderTop: '1px solid var(--edge)' }}
    >
      <h3 className="nb-label" style={{ marginBottom: 6 }}>
        Method
      </h3>
      <p style={{ fontSize: 12, color: 'var(--muted)', maxWidth: '84ch', marginBottom: 10 }}>
        Contributions are Shapley values computed with TreeSHAP over the fitted tree
        ensemble — the exact polynomial-time algorithm for trees, not a sampling
        approximation. Feature-level values are summed into the concepts above, so one
        fact produces one bar instead of one per encoded column, and the sign survives
        that aggregation: positive pushes the score toward fraud, negative away from it.
      </p>
      <ul className="flex flex-col gap-2" style={{ listStyle: 'none', padding: 0, margin: 0 }}>
        {SOURCES.map((s) => (
          <li key={s.href} style={{ fontSize: 11.5, lineHeight: 1.5 }}>
            <a
              href={s.href}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-baseline gap-1"
              style={{ color: 'var(--accent)', fontWeight: 600 }}
            >
              {s.cite}
              <span style={{ transform: 'translateY(1px)' }}>
                <Icon name="external" size={11} />
              </span>
            </a>{' '}
            <span className="nb-mono" style={{ color: 'var(--faint)' }}>
              {s.where}
            </span>
            <br />
            <span style={{ color: 'var(--muted)' }}>{s.note}</span>
          </li>
        ))}
      </ul>
    </footer>
  );
}

interface XAIPanelProps {
  explanation: string | null;
  shapFeatures: SHAPFeature[] | null;
}

export function XAIPanel({ explanation, shapFeatures }: XAIPanelProps) {
  const hasData = explanation || (shapFeatures && shapFeatures.length > 0);

  return (
    <Panel title="Explanation" subtitle="Why the engine decided what it did — signed, additive contributions">
      
      {!hasData && (
        // Matches the verdict panel's empty state: left-aligned, on the shared icon
        // grid. It was a centred column round a 64px stock lightbulb drawn at a stroke
        // weight nothing else in the app uses.
        <div className="flex flex-col items-start gap-2" style={{ padding: '28px 0 36px' }}>
          <span style={{ color: 'var(--faint)' }}>
            <Icon name="database" size={26} />
          </span>
          <p className="nb-display" style={{ fontSize: 17 }}>
            No explanation yet
          </p>
          <p style={{ fontSize: 12.5, color: 'var(--muted)', maxWidth: '46ch' }}>
            Every decision carries a signed, additive breakdown of what drove it. Score a
            payment and it appears here alongside the sentence the merchant is shown.
          </p>
        </div>
      )}

      {hasData && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          {/* Explanation Text */}
          <div>
            <h3 className="nb-label" style={{ marginBottom: 8 }}>What the merchant is told</h3>
            {explanation ? (
              <div className="nb-panel p-4">
                <p className="text-[var(--ink)] leading-relaxed">{explanation}</p>
              </div>
            ) : (
              <div className="nb-panel p-4">
                <p className="text-[var(--muted)] italic">No explanation available</p>
              </div>
            )}
          </div>

          {/* SHAP Chart */}
          <div>
            <h3 className="nb-label" style={{ marginBottom: 8 }}>Contribution breakdown</h3>
            {shapFeatures && shapFeatures.length > 0 ? (
              <div className="nb-panel p-4">
                <SHAPChart features={shapFeatures} />
              </div>
            ) : (
              <div className="nb-panel p-4 flex items-center justify-center h-64">
                <p className="text-[var(--muted)] italic">No feature data available</p>
              </div>
            )}
          </div>
        </div>
      )}

      <Method />
    </Panel>
  );
}