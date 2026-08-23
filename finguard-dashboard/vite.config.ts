/// <reference types="vitest" />
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    // Threads rather than the default forked processes. Vitest's fork pool fails to
    // hand off to its workers on some Windows setups and the run dies with
    // "Timeout waiting for worker to respond" before a single test executes - which
    // reads as a broken test suite rather than a broken runner. Threads start faster
    // here anyway, and nothing in these tests needs process isolation.
    pool: 'threads',
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
    },
  },
})
