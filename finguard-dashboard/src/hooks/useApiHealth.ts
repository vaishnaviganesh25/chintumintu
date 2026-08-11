import { useEffect, useState } from 'react';
import type { ApiHealth } from '../types';
import { fetchHealth } from '../services/fraudApi';

/** Slow enough to be invisible, fast enough to notice a restarted backend. */
const POLL_INTERVAL_MS = 15_000;

/**
 * Track whether the FinGuard API is reachable and which model it has loaded.
 *
 * The first question anyone asks when a dashboard shows nothing is "is the backend
 * even running?". Answering it in the header costs one request and saves a trip to
 * the browser console.
 */
export function useApiHealth() {
  const [health, setHealth] = useState<ApiHealth | null>(null);
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;

    const poll = async () => {
      const result = await fetchHealth(controller.signal);
      if (cancelled) return;
      setHealth(result);
      setChecked(true);
    };

    void poll();
    const timer = setInterval(() => void poll(), POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      controller.abort();
      clearInterval(timer);
    };
  }, []);

  return { health, checked, isOnline: health?.model_loaded === true };
}
