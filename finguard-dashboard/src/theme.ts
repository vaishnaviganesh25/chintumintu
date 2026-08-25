/**
 * Theme resolution.
 *
 * Three states, not two: `light`, `dark`, and `system` — the last following
 * `prefers-color-scheme`. A two-state toggle silently overrides the operating system
 * preference the first time anyone touches it, and there is then no way back.
 *
 * The choice is written to `localStorage` and mirrored onto `<html data-theme>`, which
 * is what `index.css` keys on. An inline script in `index.html` applies the same value
 * before first paint; this module keeps it in step afterwards.
 */

export type Theme = 'light' | 'dark' | 'system';

const STORAGE_KEY = 'finguard-theme';

/** Reads the stored preference, tolerating storage being unavailable entirely. */
export function readTheme(): Theme {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === 'light' || stored === 'dark' || stored === 'system') return stored;
  } catch {
    /* private mode, blocked site data — fall through to the system default */
  }
  return 'system';
}

/**
 * Apply a theme and remember it.
 *
 * `system` removes the attribute rather than writing a resolved value, so the page
 * keeps following the OS if the viewer changes it while the tab is open.
 */
export function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  if (theme === 'system') {
    root.removeAttribute('data-theme');
  } else {
    root.setAttribute('data-theme', theme);
  }

  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    /* the theme still applies for this session; it just will not persist */
  }
}

/** Which theme is actually on screen, resolving `system` against the media query. */
export function resolvedTheme(theme: Theme): 'light' | 'dark' {
  if (theme !== 'system') return theme;
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}
