import { Panel } from './ui';
import { StatusBadge } from './StatusBadge';
import { RiskGauge } from './RiskGauge';
import { LatencyMetric } from './LatencyMetric';
import type { FraudDetectionResponse } from '../types';

interface EvaluationPanelProps {
  isLoading: boolean;
  results: FraudDetectionResponse | null;
  /** Calibrated decision threshold from the API, shown under the gauge. */
  threshold?: number | null;
}

export function EvaluationPanel({ isLoading, results, threshold }: EvaluationPanelProps) {
  return (
    <Panel title="Evaluation" subtitle="What the engine decided, and what each action would cost">
      
      <div className="min-h-[300px]" aria-live="polite">
        {isLoading && (
          <div className="flex flex-col gap-3" style={{ padding: '10px 0' }}>
            <div className="nb-skeleton" style={{ height: 40, width: '55%' }} aria-hidden="true" />
            <div className="nb-skeleton" style={{ height: 128 }} aria-hidden="true" />
            <p className="nb-label" role="status">Scoring…</p>
          </div>
        )}
        
        {!isLoading && !results && (
          <div className="flex items-center justify-center h-64 text-[var(--muted)]">
            <div className="text-center">
              <svg className="w-16 h-16 mx-auto mb-4 text-[var(--faint)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v10a2 2 0 002 2h8a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
              </svg>
              <p className="nb-display" style={{ fontSize: 15 }}>Awaiting input</p>
              <p style={{ fontSize: 12.5, color: 'var(--muted)', marginTop: 4 }}>Enter a payment, or replay a signature from the simulator.</p>
            </div>
          </div>
        )}
        
        {!isLoading && results && (
          <div className="space-y-6">
            {/* Merchant decision */}
            <div className="flex justify-center">
              <StatusBadge action={results.action} costs={results.action_costs} />
            </div>
            
            {/* Risk Gauge and Latency */}
            <div className="flex items-center justify-center space-x-8">
              <RiskGauge
                probability={results.fraud_probability}
                action={results.action}
                threshold={threshold}
              />
              <div className="flex flex-col space-y-2">
                <LatencyMetric executionTimeMs={results.execution_time_ms} />
                <div className="nb-mono" style={{ fontSize: 10.5, color: 'var(--faint)', textAlign: 'center' }}>
                  {results.transaction_id}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </Panel>
  );
}