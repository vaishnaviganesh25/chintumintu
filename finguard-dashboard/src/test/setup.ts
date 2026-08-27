import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';

// The /vitest entry registers the matchers *and* their type augmentation. Extending
// `expect` by hand worked at runtime but left `toBeInTheDocument` unknown to tsc, so
// `npm run build` failed the moment a test actually used one.
import '@testing-library/jest-dom/vitest';

// Cleanup after each test case
afterEach(() => {
  cleanup();
});

// jsdom ships no matchMedia, and framer-motion's useReducedMotion calls it on mount —
// without this every component test throws before it renders. Reporting reduced motion
// as ON also makes the count-up settle synchronously, so assertions read the final
// figure rather than whichever frame they happened to catch.
if (!window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: query.includes('prefers-reduced-motion'),
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as typeof window.matchMedia;
}
