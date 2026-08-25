import type { ApiHealth } from '../types';
import { API_BASE_URL } from '../services/fraudApi';
import { Icon } from './Icon';

interface ApiStatusProps {
  health: ApiHealth | null;
  checked: boolean;
}

/**
 * Connection badge for the backend.
 *
 * The first question anyone asks when a panel shows nothing is whether the backend is
 * even running. Answering it here costs one request and saves a trip to the console —
 * and when it is down, the badge names the address and the command rather than leaving
 * the reader to guess which of the two processes died.
 */
export function ApiStatus({ health, checked }: ApiStatusProps) {
  const base = 'inline-flex items-center gap-2 fg-mono';
  const dot = (tone: string, pulse = false) => (
    <span
      style={{
        width: 6,
        height: 6,
        borderRadius: 999,
        background: tone,
        animation: pulse ? 'pulse 1.6s ease-in-out infinite' : undefined,
      }}
    />
  );

  if (!checked) {
    return (
      <span className={base} style={{ fontSize: 11, color: 'var(--faint)' }}>
        {dot('var(--faint)', true)}
        Connecting
      </span>
    );
  }

  if (!health?.model_loaded) {
    return (
      <span
        className={base}
        style={{ fontSize: 11, color: 'var(--hold)' }}
        title={`No model available at ${API_BASE_URL}. Start it with \`python main.py\`.`}
      >
        <Icon name="alert" size={13} />
        Engine offline
      </span>
    );
  }

  return (
    <span
      className={base}
      style={{ fontSize: 11, color: 'var(--muted)' }}
      title={health.trained_at ? `Model trained ${health.trained_at}` : undefined}
    >
      {dot('var(--accept)')}
      <span style={{ color: 'var(--accept)' }}>Online</span>
    </span>
  );
}
