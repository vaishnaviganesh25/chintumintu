import type { ApiHealth } from '../types';
import { API_BASE_URL } from '../services/fraudApi';

interface ApiStatusProps {
  health: ApiHealth | null;
  checked: boolean;
}

/** Connection badge for the backend, so a dead API is obvious rather than mysterious. */
export function ApiStatus({ health, checked }: ApiStatusProps) {
  if (!checked) {
    return (
      <span className="inline-flex items-center gap-2 text-xs text-gray-500">
        <span className="w-2 h-2 rounded-full bg-gray-500 animate-pulse" />
        Connecting to engine…
      </span>
    );
  }

  if (!health?.model_loaded) {
    return (
      <span
        className="inline-flex items-center gap-2 text-xs text-red-400"
        title={`No model available at ${API_BASE_URL}. Run \`python main.py\`.`}
      >
        <span className="w-2 h-2 rounded-full bg-red-500" />
        Engine offline — {API_BASE_URL}
      </span>
    );
  }

  return (
    <span
      className="inline-flex items-center gap-2 text-xs text-gray-400"
      title={health.trained_at ? `Model trained ${health.trained_at}` : undefined}
    >
      <span className="w-2 h-2 rounded-full bg-green-500" />
      <span className="text-green-400">Engine online</span>
      <span className="text-gray-600">|</span>
      {health.model_name}
      {typeof health.threshold === 'number' && (
        <>
          <span className="text-gray-600">|</span>
          threshold {health.threshold.toFixed(4)}
        </>
      )}
    </span>
  );
}
