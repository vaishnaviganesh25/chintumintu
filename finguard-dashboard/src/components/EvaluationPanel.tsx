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
    <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
      <h2 className="text-xl font-semibold text-cyan-400 mb-6">Evaluation Results</h2>
      
      <div className="min-h-[300px]" aria-live="polite">
        {isLoading && (
          <div className="flex flex-col items-center justify-center h-64">
            <LoadingSpinner />
            <p className="text-gray-400 mt-4">Analyzing transaction...</p>
          </div>
        )}
        
        {!isLoading && !results && (
          <div className="flex items-center justify-center h-64 text-gray-400">
            <div className="text-center">
              <svg className="w-16 h-16 mx-auto mb-4 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v10a2 2 0 002 2h8a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
              </svg>
              <p className="text-lg">Awaiting input...</p>
              <p className="text-sm text-gray-500 mt-1">Enter transaction details to begin analysis</p>
            </div>
          </div>
        )}
        
        {!isLoading && results && (
          <div className="space-y-6">
            {/* Status Badge */}
            <div className="flex justify-center">
              <StatusBadge status={results.status} />
            </div>
            
            {/* Risk Gauge and Latency */}
            <div className="flex items-center justify-center space-x-8">
              <RiskGauge
                probability={results.fraud_probability}
                status={results.status}
                threshold={threshold}
              />
              <div className="flex flex-col space-y-2">
                <LatencyMetric executionTimeMs={results.execution_time_ms} />
                <div className="text-xs text-gray-500 text-center">
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