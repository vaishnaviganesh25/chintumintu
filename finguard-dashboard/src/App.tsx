import { useState } from 'react';
import { AppShell, type ViewId } from './components/AppShell';
import { TransactionSimulator } from './components/TransactionSimulator';
import { EvaluationPanel } from './components/EvaluationPanel';
import { XAIPanel } from './components/XAIPanel';
import { OpsConsole } from './components/OpsConsole';
import { RingGraph } from './components/RingGraph';
import { ModelCard } from './components/ModelCard';
import { useFraudSimulation } from './hooks/useFraudSimulation';
import { useApiHealth } from './hooks/useApiHealth';

function App() {
  const [view, setView] = useState<ViewId>('simulator');
  const { isLoading, results, error, simulateTransaction } = useFraudSimulation();
  const { health } = useApiHealth();

  return (
    <AppShell
      view={view}
      onNavigate={setView}
      modelName={health?.model_name}
      threshold={health?.threshold}
    >
      {view === 'simulator' && (
        <div className="flex flex-col gap-5">
          {error && (
            <div
              role="alert"
              className="fg-surface px-4 py-3"
              style={{
                borderColor: 'var(--hold)',
                background: 'var(--hold-soft)',
                color: 'var(--hold)',
                fontSize: 13,
              }}
            >
              <strong style={{ fontWeight: 600 }}>Scoring failed. </strong>
              {error}
            </div>
          )}

          <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
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
        </div>
      )}

      {view === 'desk' && <OpsConsole />}
      {view === 'rings' && <RingGraph />}
      {view === 'model' && <ModelCard />}
    </AppShell>
  );
}

export default App;
