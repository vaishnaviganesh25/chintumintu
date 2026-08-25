import { useEffect, useState, type ReactNode } from 'react';
import { Icon, type IconName } from './Icon';
import { applyTheme, readTheme, type Theme } from '../theme';
import { fetchDeepHealth, setModelDisabled } from '../services/opsApi';
import type { DeepHealth } from '../types';

/**
 * The application frame: a persistent left rail, a status bar, and the active view.
 *
 * A rail rather than a tab strip. Tabs read as sections of a page; a rail reads as an
 * application with places in it, and this product has four genuinely different jobs —
 * scoring a payment, working a queue, investigating a ring, and reading the model's
 * own card.
 */

export type ViewId = 'simulator' | 'desk' | 'rings' | 'model';

interface NavEntry {
  id: ViewId;
  label: string;
  icon: IconName;
  hint: string;
}

const NAV: NavEntry[] = [
  { id: 'simulator', label: 'Simulator', icon: 'flask', hint: 'Score a payment against the live model' },
  { id: 'desk', label: 'Fraud desk', icon: 'inbox', hint: 'Work the alert queue' },
  { id: 'rings', label: 'Ring graph', icon: 'network', hint: 'Investigate a mule ring' },
  { id: 'model', label: 'Model card', icon: 'file-text', hint: 'What shipped, and what it cost' },
];

const THEME_CYCLE: Theme[] = ['system', 'light', 'dark'];
const THEME_ICON: Record<Theme, IconName> = { system: 'monitor', light: 'sun', dark: 'moon' };

function ThemeSwitch() {
  const [theme, setTheme] = useState<Theme>(() => readTheme());

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const next = THEME_CYCLE[(THEME_CYCLE.indexOf(theme) + 1) % THEME_CYCLE.length];

  return (
    <button
      type="button"
      onClick={() => setTheme(next)}
      className="fg-btn"
      style={{ padding: '6px 9px' }}
      // The label names the current state and the action, so a screen-reader user is
      // not left guessing which of three states a single button is in.
      aria-label={`Theme: ${theme}. Switch to ${next}.`}
      title={`Theme: ${theme} — click for ${next}`}
    >
      <Icon name={THEME_ICON[theme]} size={15} />
    </button>
  );
}

/**
 * Which rung of the degradation ladder is answering, and — when the chaos endpoint is
 * enabled — the switch that proves it works.
 *
 * A silent fallback is the failure this exists to prevent. If the model goes and
 * nothing says so, the alert rate moves and everyone concludes the world changed.
 */
function RungStatus() {
  const [health, setHealth] = useState<DeepHealth | null>(null);
  const [busy, setBusy] = useState(false);

  const poll = async () => setHealth(await fetchDeepHealth());

  useEffect(() => {
    void poll();
    const timer = setInterval(() => void poll(), 8_000);
    return () => clearInterval(timer);
  }, []);

  if (!health) {
    return (
      <span className="fg-label" style={{ color: 'var(--faint)' }}>
        API unreachable
      </span>
    );
  }

  const modelDown = health.dependencies.model?.status !== 'ok';
  const tone = health.serving ? 'var(--accept)' : 'var(--challenge)';

  const toggle = async () => {
    setBusy(true);
    try {
      await setModelDisabled(!modelDown);
      await poll();
    } catch {
      /* 403 when chaos is disabled server-side is expected, not an error state */
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex items-center gap-2">
      <span
        className="inline-flex items-center gap-2 fg-mono"
        style={{
          fontSize: 11,
          color: tone,
          background: health.serving ? 'var(--accept-soft)' : 'var(--challenge-soft)',
          border: `1px solid ${tone}`,
          borderRadius: 'var(--radius-sm)',
          padding: '3px 8px',
        }}
        title="Which rung of the degradation ladder is answering right now"
      >
        <span
          style={{ width: 5, height: 5, borderRadius: 99, background: tone, display: 'inline-block' }}
        />
        {health.rung_label}
      </span>

      {health.chaos_endpoint_enabled && (
        <button
          type="button"
          onClick={() => void toggle()}
          disabled={busy}
          className="fg-btn"
          style={{ padding: '5px 9px', fontSize: 12 }}
          title={modelDown ? 'Bring the model back' : 'Disable the model and watch the ladder'}
        >
          <Icon name="power" size={14} />
          {modelDown ? 'Restore' : 'Kill model'}
        </button>
      )}
    </div>
  );
}

interface AppShellProps {
  view: ViewId;
  onNavigate: (view: ViewId) => void;
  modelName?: string | null;
  threshold?: number | null;
  children: ReactNode;
}

export function AppShell({ view, onNavigate, modelName, threshold, children }: AppShellProps) {
  const active = NAV.find((entry) => entry.id === view);

  return (
    <div className="min-h-screen flex" style={{ background: 'var(--ground)' }}>
      {/* Rail ------------------------------------------------------------- */}
      <nav
        aria-label="Sections"
        className="hidden md:flex flex-col shrink-0"
        style={{
          width: 216,
          background: 'var(--surface)',
          borderRight: '1px solid var(--rule)',
        }}
      >
        <div
          className="flex items-center gap-2.5 px-5"
          style={{ height: 60, borderBottom: '1px solid var(--rule)' }}
        >
          <span style={{ color: 'var(--accent)', display: 'flex' }}>
            <Icon name="shield" size={21} />
          </span>
          <span style={{ fontSize: 16, fontWeight: 600, letterSpacing: '-0.015em' }}>
            FinGuard
          </span>
        </div>

        <ul className="flex flex-col gap-0.5 p-2.5">
          {NAV.map((entry) => {
            const selected = entry.id === view;
            return (
              <li key={entry.id}>
                <button
                  type="button"
                  onClick={() => onNavigate(entry.id)}
                  aria-current={selected ? 'page' : undefined}
                  title={entry.hint}
                  className="w-full flex items-center gap-2.5 text-left"
                  style={{
                    padding: '8px 11px',
                    borderRadius: 'var(--radius-sm)',
                    fontSize: 13,
                    fontWeight: selected ? 600 : 400,
                    color: selected ? 'var(--accent)' : 'var(--muted)',
                    background: selected ? 'var(--accent-soft)' : 'transparent',
                    border: 'none',
                    cursor: 'pointer',
                  }}
                >
                  <Icon name={entry.icon} size={16} />
                  {entry.label}
                </button>
              </li>
            );
          })}
        </ul>

        <div className="mt-auto p-4" style={{ borderTop: '1px solid var(--rule)' }}>
          <p className="fg-label" style={{ marginBottom: 3 }}>Model</p>
          <p className="fg-mono" style={{ fontSize: 12, color: 'var(--muted)' }}>
            {modelName ?? 'not loaded'}
          </p>
          {typeof threshold === 'number' && (
            <p className="fg-mono" style={{ fontSize: 11, color: 'var(--faint)', marginTop: 2 }}>
              holds at {threshold.toFixed(4)}
            </p>
          )}
        </div>
      </nav>

      {/* Content ---------------------------------------------------------- */}
      <div className="flex-1 min-w-0 flex flex-col">
        <header
          className="flex items-center justify-between gap-4 px-6 shrink-0"
          style={{
            height: 60,
            background: 'var(--surface)',
            borderBottom: '1px solid var(--rule)',
          }}
        >
          <div className="min-w-0">
            <h1 style={{ fontSize: 15, fontWeight: 600, letterSpacing: '-0.01em' }}>
              {active?.label ?? 'FinGuard'}
            </h1>
            <p style={{ fontSize: 12, color: 'var(--muted)' }} className="truncate">
              {active?.hint}
            </p>
          </div>

          <div className="flex items-center gap-2.5 shrink-0">
            <RungStatus />
            <ThemeSwitch />
          </div>
        </header>

        {/* Rail collapses on narrow screens; the sections still need to be reachable. */}
        <nav
          aria-label="Sections"
          className="flex md:hidden gap-1 px-3 py-2 overflow-x-auto shrink-0"
          style={{ background: 'var(--surface)', borderBottom: '1px solid var(--rule)' }}
        >
          {NAV.map((entry) => (
            <button
              key={entry.id}
              type="button"
              onClick={() => onNavigate(entry.id)}
              aria-current={entry.id === view ? 'page' : undefined}
              className="fg-btn shrink-0"
              style={{
                fontSize: 12,
                color: entry.id === view ? 'var(--accent)' : 'var(--muted)',
                borderColor: entry.id === view ? 'var(--accent)' : 'var(--rule-strong)',
              }}
            >
              <Icon name={entry.icon} size={14} />
              {entry.label}
            </button>
          ))}
        </nav>

        <main className="flex-1 p-6 min-w-0">{children}</main>
      </div>
    </div>
  );
}
