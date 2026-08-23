import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './index.css';
import App from './App.tsx';

/**
 * Accessibility auditing, development builds only.
 *
 * axe walks the rendered tree and reports WCAG violations to the console with the
 * offending node attached, which catches the failures that are invisible in review:
 * a colour pair that drops under 4.5:1, an input whose label was refactored away,
 * a live region that never announces. It is loaded through a dynamic import behind
 * an `import.meta.env.DEV` guard so neither the library nor its rule set is included
 * in the production bundle.
 */
if (import.meta.env.DEV) {
  void (async () => {
    const [{ default: axe }, React, ReactDOM] = await Promise.all([
      import('@axe-core/react'),
      import('react'),
      import('react-dom'),
    ]);
    // The delay debounces axe against React's own re-render bursts; without it every
    // keystroke in the form triggers a full tree audit.
    await axe(React, ReactDOM, 1000);
  })();
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
