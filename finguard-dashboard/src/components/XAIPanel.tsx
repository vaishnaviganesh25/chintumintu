import { SHAPChart } from './SHAPChart';
import { Icon } from './Icon';
import { Panel } from './ui';
import type { SHAPFeature } from '../types';

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
    </Panel>
  );
}