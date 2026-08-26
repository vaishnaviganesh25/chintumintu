import { useEffect, useState, type ReactNode } from 'react';
import { motion } from 'framer-motion';
import { Icon, type IconName } from './Icon';
import { Logotype } from './Marks';
import { Button } from './ui';
import { SPRING, useReducedMotion } from '../motion';
import { applyTheme, readTheme, type Theme } from '../theme';
import { fetchDeepHealth, setModelDisabled } from '../services/opsApi';
import type { DeepHealth } from '../types';

/**
 * The frame: a solid bordered rail, a glass top bar, and the active view.
 *
 * A rail rather than tabs. Tabs read as sections of a page; a rail reads as an
 * application with places in it, and this product has four genuinely different jobs —
 * score a payment, work a queue, investigate a ring, read the model's own card.
 *
 * The top bar is the one piece of chrome that is glass rather than solid, because it
 * is the only piece that content scrolls underneath.
 */

export type ViewId = 'simulator' | 'desk' | 'rings' | 'model';

const NAV: { id: ViewId; label: string; icon: IconName; hint: string }[] = [
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
    <Button
      onClick={() => setTheme(next)}
      // Names the current state and the action, so a screen-reader user is not left
      // guessing which of three states one button is in.
      aria-label={`Theme: ${theme}. Switch to ${next}.`}
      title={`Theme: ${theme} — click for ${next}`}
      style={{ padding: '7px 9px' }}
    >
      <Icon name={THEME_ICON[theme]} size={15} />
    </Button>
  );
}

/**
 * Which rung of the degradation ladder is answering, and the switch that proves it.
 *
 * A silent fallback is the failure this exists to prevent: if the model goes and
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
    return <span className="nb-label">API unreachable</span>;
  }

  const modelDown = health.dependencies.model?.status !== 'ok';
  const fill = health.serving ? 'var(--accept-fill)' : 'var(--challenge-fill)';

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
        className="nb-mono inline-flex items-center gap-2"
        style={{
          fontSize: 11,
          fontWeight: 700,
          color: '#0b0b0b',
          background: fill,
          border: 'var(--border)',
          borderRadius: 999,
          padding: '3px 10px',
        }}
        title="Which rung of the degradation ladder is answering right now"
      >
        <motion.span
          animate={health.serving ? {} : { opacity: [1, 0.35, 1] }}
          transition={{ repeat: Infinity, duration: 1.6 }}
          style={{ width: 6, height: 6, borderRadius: 999, background: '#0b0b0b' }}
        />
        {health.rung_label}
      </span>

      {health.chaos_endpoint_enabled && (
        <Button
          variant={modelDown ? 'primary' : 'danger'}
          icon="power"
          onClick={() => void toggle()}
          disabled={busy}
          style={{ fontSize: 12, padding: '6px 10px' }}
          title={modelDown ? 'Bring the model back' : 'Disable the model and watch the ladder'}
        >
          {modelDown ? 'Restore' : 'Kill model'}
        </Button>
      )}
    </div>
  );
}

export function AppShell({
  view,
  onNavigate,
  modelName,
  threshold,
  children,
}: {
  view: ViewId;
  onNavigate: (view: ViewId) => void;
  modelName?: string | null;
  threshold?: number | null;
  children: ReactNode;
}) {
  const reduced = useReducedMotion();
  const active = NAV.find((entry) => entry.id === view);

  return (
    <div className="min-h-screen flex" style={{ background: 'var(--paper)' }}>
      {/* Rail --------------------------------------------------------------- */}
      <nav
        aria-label="Sections"
        className="hidden md:flex flex-col shrink-0"
        style={{
          width: 232,
          background: 'var(--surface)',
          borderRight: 'var(--border)',
        }}
      >
        <div
          className="flex items-center px-5"
          style={{ height: 66, borderBottom: 'var(--border)' }}
        >
          <Logotype />
        </div>

        <ul className="flex flex-col gap-1.5 p-3">
          {NAV.map((entry) => {
            const selected = entry.id === view;
            return (
              <li key={entry.id} className="relative">
                <button
                  type="button"
                  onClick={() => onNavigate(entry.id)}
                  aria-current={selected ? 'page' : undefined}
                  title={entry.hint}
                  className="w-full flex items-center gap-2.5 text-left relative"
                  style={{
                    padding: '9px 12px',
                    borderRadius: 'var(--radius-sm)',
                    border: selected ? 'var(--border)' : 'var(--border-w) solid transparent',
                    boxShadow: selected ? 'var(--shadow-hard-sm)' : 'none',
                    background: selected ? 'var(--accent)' : 'transparent',
                    color: selected ? 'var(--accent-ink)' : 'var(--muted)',
                    fontSize: 13.5,
                    fontWeight: selected ? 700 : 500,
                    cursor: 'pointer',
                    transition: 'background-color var(--dur-fast), color var(--dur-fast)',
                  }}
                >
                  <Icon name={entry.icon} size={17} />
                  {entry.label}
                </button>
              </li>
            );
          })}
        </ul>

        <div className="mt-auto p-4" style={{ borderTop: 'var(--border)' }}>
          <p className="nb-label" style={{ marginBottom: 3 }}>
            Model
          </p>
          <p className="nb-mono" style={{ fontSize: 12, color: 'var(--ink)', fontWeight: 500 }}>
            {modelName ?? 'not loaded'}
          </p>
          {typeof threshold === 'number' && (
            <p className="nb-mono" style={{ fontSize: 11, color: 'var(--muted)', marginTop: 1 }}>
              holds at {threshold.toFixed(4)}
            </p>
          )}
        </div>
      </nav>

      {/* Content ------------------------------------------------------------ */}
      <div className="flex-1 min-w-0 flex flex-col">
        <header
          className="nb-glass flex items-center justify-between gap-4 px-6 shrink-0 sticky top-0"
          style={{
            height: 66,
            zIndex: 30,
            borderTop: 'none',
            borderLeft: 'none',
            borderRight: 'none',
            borderRadius: 0,
          }}
        >
          <div className="min-w-0">
            <h1 className="nb-display" style={{ fontSize: 17, lineHeight: 1.15 }}>
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

        {/* The rail collapses on narrow screens; sections still have to be reachable. */}
        <nav
          aria-label="Sections"
          className="flex md:hidden gap-2 px-4 py-3 overflow-x-auto shrink-0"
          style={{ background: 'var(--surface)', borderBottom: 'var(--border)' }}
        >
          {NAV.map((entry) => (
            <Button
              key={entry.id}
              variant={entry.id === view ? 'primary' : 'default'}
              icon={entry.icon}
              onClick={() => onNavigate(entry.id)}
              aria-current={entry.id === view ? 'page' : undefined}
              className="shrink-0"
              style={{ fontSize: 12 }}
            >
              {entry.label}
            </Button>
          ))}
        </nav>

        {/* Keyed on the view so each one animates in rather than swapping in place. */}
        <motion.main
          key={view}
          initial={reduced ? { opacity: 0 } : { opacity: 0, y: 10 }}
          animate={reduced ? { opacity: 1 } : { opacity: 1, y: 0 }}
          transition={reduced ? { duration: 0.15 } : SPRING}
          className="flex-1 min-w-0"
          // NN/g: 24–32px between blocks, so density does not become clutter.
          style={{ padding: 26 }}
        >
          {children}
        </motion.main>
      </div>
    </div>
  );
}
