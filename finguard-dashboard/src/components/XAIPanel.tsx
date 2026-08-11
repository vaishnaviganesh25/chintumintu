import { SHAPChart } from './SHAPChart';
import type { SHAPFeature } from '../types';

interface XAIPanelProps {
  explanation: string | null;
  shapFeatures: SHAPFeature[] | null;
}

export function XAIPanel({ explanation, shapFeatures }: XAIPanelProps) {
  const hasData = explanation || (shapFeatures && shapFeatures.length > 0);

  return (
    <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
      <h2 className="text-xl font-semibold text-cyan-400 mb-6">Explainable AI Analysis</h2>
      
      {!hasData && (
        <div className="flex items-center justify-center h-64 text-gray-400">
          <div className="text-center">
            <svg className="w-16 h-16 mx-auto mb-4 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
            </svg>
            <p className="text-lg">No analysis data available</p>
            <p className="text-sm text-gray-500 mt-1">Run a transaction simulation to see explanations</p>
          </div>
        </div>
      )}

      {hasData && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          {/* Explanation Text */}
          <div>
            <h3 className="text-lg font-medium text-gray-300 mb-4">Fraud Detection Explanation</h3>
            {explanation ? (
              <div className="bg-gray-700/50 rounded-lg p-4 border border-gray-600">
                <p className="text-gray-300 leading-relaxed">{explanation}</p>
              </div>
            ) : (
              <div className="bg-gray-700/30 rounded-lg p-4 border border-gray-600">
                <p className="text-gray-400 italic">No explanation available</p>
              </div>
            )}
          </div>

          {/* SHAP Chart */}
          <div>
            <h3 className="text-lg font-medium text-gray-300 mb-4">Feature Importance Analysis</h3>
            {shapFeatures && shapFeatures.length > 0 ? (
              <div className="bg-gray-700/50 rounded-lg p-4 border border-gray-600">
                <SHAPChart features={shapFeatures} />
              </div>
            ) : (
              <div className="bg-gray-700/30 rounded-lg p-4 border border-gray-600 flex items-center justify-center h-64">
                <p className="text-gray-400 italic">No feature data available</p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}