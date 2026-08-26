import { SHAPChart } from './SHAPChart';
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
        <div className="flex items-center justify-center h-64 text-[var(--muted)]">
          <div className="text-center">
            <svg className="w-16 h-16 mx-auto mb-4 text-[var(--faint)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
            </svg>
            <p className="nb-display" style={{ fontSize: 15 }}>No explanation yet</p>
            <p style={{ fontSize: 12.5, color: 'var(--muted)', marginTop: 4 }}>Score a payment to see what drove the decision.</p>
          </div>
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