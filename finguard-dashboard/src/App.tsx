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
import { Notice } from './components/ui';

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
        <div className="flex flex-col gap-6">
          {error && (
            <Notice tone="hold" icon="alert">
              <strong style={{ fontWeight: 700 }}>Scoring failed. </strong>
              {error}
            </Notice>
          )}

          {/* The simulator is a tall form; the verdict and the explanation are each
              short. Side by side at equal width the right column ran out of content
              and left a hole at the bottom of the viewport. Stacking the two outputs
              in a wider right column lets them fill the form's height instead. */}
          <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] gap-6 items-start">
            <TransactionSimulator onSimulate={simulateTransaction} isLoading={isLoading} />

            <div className="flex flex-col gap-6 min-w-0">
              <EvaluationPanel
                isLoading={isLoading}
                results={results}
                threshold={health?.threshold}
              />
              <XAIPanel
                explanation={results?.xai_explanation || null}
                shapFeatures={results?.shap_features || null}
              />
            </div>
          </div>
        </div>
      )}

      {view === 'desk' && <OpsConsole />}
      {view === 'rings' && <RingGraph />}
      {view === 'model' && <ModelCard />}
    </AppShell>
  );
}

export default App;
