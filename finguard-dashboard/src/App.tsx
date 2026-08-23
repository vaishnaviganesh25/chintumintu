import { useEffect, useState } from 'react';
import './App.css';
import { TransactionSimulator } from './components/TransactionSimulator';
import { EvaluationPanel } from './components/EvaluationPanel';
import { XAIPanel } from './components/XAIPanel';
import { ApiStatus } from './components/ApiStatus';
import { OpsConsole } from './components/OpsConsole';
import { useFraudSimulation } from './hooks/useFraudSimulation';
import { useApiHealth } from './hooks/useApiHealth';
import { fetchDeepHealth, setModelDisabled } from './services/opsApi';
import type { DeepHealth } from './types';

type Tab = 'simulate' | 'desk';

/**
 * Header strip showing which rung the engine is answering on.
 *
 * A silent fallback is the failure mode this exists to prevent: if the model goes and
 * nothing says so, the alert rate moves and everyone assumes the world changed rather
 * than the engine. When the chaos endpoint is enabled the strip also carries the
 * switch, so the ladder can be demonstrated rather than described.
 */
function RungIndicator() {
  const [health, setHealth] = useState<DeepHealth | null>(null);
  const [busy, setBusy] = useState(false);

  const poll = async () => setHealth(await fetchDeepHealth());

  useEffect(() => {
    void poll();
    const timer = setInterval(() => void poll(), 8_000);
    return () => clearInterval(timer);
  }, []);

  if (!health) return null;

  const modelDown = health.dependencies.model?.status !== 'ok';

  const toggle = async () => {
    setBusy(true);
    try {
      await setModelDisabled(!modelDown);
      await poll();
    } catch {
      /* the 403 when chaos is disabled server-side is expected, not an error state */
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex items-center gap-3">
      <span
        className={`inline-flex items-center gap-2 text-xs px-2.5 py-1 rounded border ${
          health.serving
            ? 'border-gray-600 bg-gray-800 text-gray-300'
            : 'border-amber-600 bg-amber-950/40 text-amber-300'
        }`}
        title="Which rung of the degradation ladder is answering right now"
      >
        <span
          className={`w-1.5 h-1.5 rounded-full ${
            health.serving ? 'bg-green-400' : 'bg-amber-400'
          }`}
        />
        {health.rung_label}
      </span>

      {health.chaos_endpoint_enabled && (
        <button
          type="button"
          onClick={() => void toggle()}
          disabled={busy}
          className="text-xs px-2.5 py-1 rounded border border-gray-600 bg-gray-800 text-gray-400 hover:text-gray-200 hover:border-gray-500 disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-cyan-500"
        >
          {modelDown ? 'Restore model' : 'Kill model'}
        </button>
      )}
    </div>
  );
}

function App() {
  const [tab, setTab] = useState<Tab>('simulate');
  const { isLoading, results, error, simulateTransaction } = useFraudSimulation();
  const { health } = useApiHealth();

  const tabClass = (name: Tab) =>
    `px-4 py-2 text-sm font-medium rounded-md transition-colors focus:outline-none focus:ring-2 focus:ring-cyan-500 ${
      tab === name
        ? 'bg-cyan-600 text-white'
        : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800'
    }`;

  return (
    <div className="min-h-screen bg-gray-900">
      <header className="bg-gray-900 border-b border-cyan-500 py-6 px-8">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-4xl font-bold text-cyan-400">FinGuard</h1>
            <p className="text-gray-400 text-sm">
              Merchant payment risk — detect, decide, defend
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <RungIndicator />
            <ApiStatus health={health} checked />
          </div>
        </div>

        <nav className="flex gap-2 mt-5" aria-label="Views">
          <button type="button" className={tabClass('simulate')} onClick={() => setTab('simulate')}>
            Simulator
          </button>
          <button type="button" className={tabClass('desk')} onClick={() => setTab('desk')}>
            Fraud desk
          </button>
        </nav>
      </header>

      <main className="container mx-auto p-6 max-w-7xl">
        {error && tab === 'simulate' && (
          <div
            className="mb-6 bg-red-900/30 border border-red-500 text-red-400 px-4 py-3 rounded-lg"
            role="alert"
          >
            <strong className="font-bold">Analysis failed: </strong>
            <span>{error}</span>
          </div>
        )}

        {tab === 'simulate' ? (
          <>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
              <TransactionSimulator onSimulate={simulateTransaction} isLoading={isLoading} />
              <EvaluationPanel
                isLoading={isLoading}
                results={results}
                threshold={health?.threshold}
              />
            </div>
            <XAIPanel
              explanation={results?.xai_explanation || null}
              shapFeatures={results?.shap_features || null}
            />
          </>
        ) : (
          <OpsConsole />
        )}
      </main>

      <footer className="border-t border-gray-700 py-6 px-8 mt-12">
        <div className="text-center text-gray-500 text-sm">
          <p>
            Every decision is scored, explained, and written to an append-only ledger —
            replayable months later, with the model version that produced it.
          </p>
        </div>
      </footer>
    </div>
  );
}

export default App;
