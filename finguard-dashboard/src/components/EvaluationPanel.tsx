import { LoadingSpinner } from './LoadingSpinner';
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
    <div className="fg-surface p-5">
      <h2 className="text-[13px] font-semibold mb-4">Evaluation Results</h2>
      
      <div className="min-h-[300px]" aria-live="polite">
        {isLoading && (
          <div className="flex flex-col items-center justify-center h-64">
            <LoadingSpinner />
            <p className="text-[var(--muted)] mt-4">Analyzing transaction...</p>
          </div>
        )}
        
        {!isLoading && !results && (
          <div className="flex items-center justify-center h-64 text-[var(--muted)]">
            <div className="text-center">
              <svg className="w-16 h-16 mx-auto mb-4 text-[var(--faint)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v10a2 2 0 002 2h8a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
              </svg>
              <p className="text-lg">Awaiting input...</p>
              <p className="text-sm text-[var(--faint)] mt-1">Enter transaction details to begin analysis</p>
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
                <div className="text-xs text-[var(--faint)] text-center">
                  Transaction ID: {results.transaction_id}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}