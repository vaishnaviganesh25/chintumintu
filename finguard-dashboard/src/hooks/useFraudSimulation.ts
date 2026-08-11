import { useCallback, useEffect, useRef, useState } from 'react';
import type { TransactionInput, FraudDetectionResponse } from '../types';
import { analyzeTransaction } from '../services/fraudApi';

export function useFraudSimulation() {
  const [isLoading, setIsLoading] = useState(false);
  const [results, setResults] = useState<FraudDetectionResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  // A second submit while the first is in flight must not be able to paint a stale
  // verdict over a newer one. Aborting the previous request makes the last submit
  // authoritative regardless of the order the responses come back in.
  const inFlight = useRef<AbortController | null>(null);

  useEffect(() => () => inFlight.current?.abort(), []);

  const simulateTransaction = useCallback(async (input: TransactionInput) => {
    inFlight.current?.abort();
    const controller = new AbortController();
    inFlight.current = controller;

    setIsLoading(true);
    setError(null);

    try {
      const response = await analyzeTransaction(input, controller.signal);
      if (!controller.signal.aborted) {
        setResults(response);
      }
    } catch (err) {
      // A request we cancelled ourselves is not a failure to report.
      if (controller.signal.aborted) return;
      setError(err instanceof Error ? err.message : 'An unexpected error occurred');
      setResults(null);
      console.error('Transaction analysis failed:', err);
    } finally {
      if (inFlight.current === controller) {
        inFlight.current = null;
        setIsLoading(false);
      }
    }
  }, []);

  const clearResults = useCallback(() => {
    inFlight.current?.abort();
    setResults(null);
    setError(null);
  }, []);

  return {
    isLoading,
    results,
    error,
    simulateTransaction,
    clearResults,
  };
}
