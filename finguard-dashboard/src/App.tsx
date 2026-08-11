import './App.css';
import { TransactionSimulator } from './components/TransactionSimulator';
import { EvaluationPanel } from './components/EvaluationPanel';
import { XAIPanel } from './components/XAIPanel';
import { ApiStatus } from './components/ApiStatus';
import { useFraudSimulation } from './hooks/useFraudSimulation';
import { useApiHealth } from './hooks/useApiHealth';

function App() {
  const { isLoading, results, error, simulateTransaction } = useFraudSimulation();
  const { health, checked } = useApiHealth();

  return (
    <div className="min-h-screen bg-gray-900">
      {/* Header */}
      <header className="bg-gray-900 border-b border-cyan-500 py-6 px-8">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-4xl font-bold text-cyan-400">FinGuard</h1>
            <p className="text-gray-400 text-sm">
              Real-Time UPI Fraud Detection Engine
            </p>
          </div>
          <ApiStatus health={health} checked={checked} />
        </div>
      </header>

      {/* Main Dashboard */}
      <main className="container mx-auto p-6 max-w-7xl">
        {/* Error Display */}
        {error && (
          <div className="mb-6 bg-red-900/30 border border-red-500 text-red-400 px-4 py-3 rounded-lg" role="alert">
            <strong className="font-bold">Analysis failed: </strong>
            <span>{error}</span>
          </div>
        )}

        {/* Main Dashboard Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
          {/* Left Column - Transaction Simulator */}
          <TransactionSimulator 
            onSimulate={simulateTransaction}
            isLoading={isLoading}
          />

          {/* Right Column - Evaluation Panel */}
          <EvaluationPanel 
            isLoading={isLoading}
            results={results}
            threshold={health?.threshold}
          />
        </div>

        {/* Bottom Row - XAI Panel (Full Width) */}
        <XAIPanel 
          explanation={results?.xai_explanation || null}
          shapFeatures={results?.shap_features || null}
        />
      </main>

      {/* Footer */}
      <footer className="border-t border-gray-700 py-6 px-8 mt-12">
        <div className="text-center text-gray-500 text-sm">
          <p>FinGuard Fraud Detection Dashboard • Built with React, TypeScript, and Tailwind CSS</p>
          <p className="mt-1">
            Live scoring by the FinGuard ML engine • SHAP explanations generated per transaction
          </p>
        </div>
      </footer>
    </div>
  );
}

export default App;
