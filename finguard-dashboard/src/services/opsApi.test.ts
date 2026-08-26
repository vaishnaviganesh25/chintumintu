import { describe, expect, it } from 'vitest';
import { isAbortError } from './opsApi';

/**
 * Cancellation is not failure.
 *
 * React 19's StrictMode mounts an effect, tears it down, and mounts it again. The
 * teardown aborts whatever request the first mount started, so a component that treats
 * every rejection as an error paints `signal is aborted without reason` over itself on
 * load — which is exactly what the Model card and Ring graph views did. It is not a
 * dev-only artifact either: the same rejection happens in production any time someone
 * switches view before a request settles.
 *
 * These tests pin the discriminator rather than the components, because the bug was
 * never in one component. It was in expecting every future caller to remember.
 */
describe('isAbortError', () => {
  it('recognises the DOMException a fetch abort actually throws', () => {
    expect(isAbortError(new DOMException('signal is aborted without reason', 'AbortError'))).toBe(
      true,
    );
  });

  it('recognises an abort however the runtime words it', () => {
    // The message differs between browsers and Node versions, and has changed across
    // releases of both. Matching on one exact string would work until it silently did
    // not, so the name is checked first and the wording only as a fallback.
    for (const message of [
      'signal is aborted without reason',
      'The user aborted a request.',
      'This operation was aborted',
      'AbortError: The operation was aborted.',
    ]) {
      expect(isAbortError(new DOMException(message, 'AbortError'))).toBe(true);
    }
  });

  it('recognises a plain Error carrying the abort name', () => {
    // Not every runtime rejects with a DOMException.
    const error = new Error('The operation was aborted');
    error.name = 'AbortError';

    expect(isAbortError(error)).toBe(true);
  });

  it('does not swallow a genuine failure', () => {
    // The half that matters more. A helper that returned true too eagerly would hide
    // real outages behind a silent, permanently-empty panel — a worse bug than the one
    // it was written to fix, and far harder to notice.
    for (const error of [
      new Error('Cannot reach the FinGuard API at http://localhost:8090'),
      new Error('503 Service Unavailable'),
      new Error('The API did not respond within 10s.'),
      new TypeError('Failed to fetch'),
      new SyntaxError('Unexpected token < in JSON'),
    ]) {
      expect(isAbortError(error)).toBe(false);
    }
  });

  it('handles rejections that are not Errors at all', () => {
    for (const value of [null, undefined, 'aborted', 42, {}, { name: 'AbortError' }]) {
      expect(isAbortError(value)).toBe(false);
    }
  });

  it('survives a real aborted fetch end to end', async () => {
    // The integration check: whatever this environment throws on a genuine abort, the
    // helper has to catch it. Asserting against a hand-built exception alone would
    // pass even if the runtime's real shape drifted.
    const controller = new AbortController();
    controller.abort();

    await expect(
      fetch('http://127.0.0.1:1/never', { signal: controller.signal }),
    ).rejects.toSatisfy(isAbortError);
  });
});
