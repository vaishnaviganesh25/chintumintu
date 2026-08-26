import { useEffect, useRef, useState } from 'react';
import { useReducedMotion, type Transition, type Variants } from 'framer-motion';

/**
 * Shared motion, defined once.
 *
 * Two things drive every choice here.
 *
 * **Springs, not durations.** A duration says "move 100px over 0.5s"; a spring says
 * "pull this with tension 200 and friction 26" and lets it settle. Interactive things
 * — a press, a drawer, a node landing — feel wrong on a fixed curve because nothing
 * physical moves that way. Non-interactive reveals still use easing, because there is
 * no gesture to respond to.
 *
 * **Every animation earns its place.** If it does not clarify, guide, or confirm, it
 * is not here. Micro-interactions sit in the 200–500 ms band: long enough to notice,
 * short enough not to sit through.
 *
 * All of it is gated on `useReducedMotion()`. Motion that cannot be turned off is an
 * accessibility defect, and the honest fallback is not "faster" — it is a plain
 * opacity fade with no movement at all.
 */

export const SPRING: Transition = { type: 'spring', stiffness: 380, damping: 30, mass: 0.8 };
export const SPRING_SOFT: Transition = { type: 'spring', stiffness: 220, damping: 28 };
export const SPRING_SNAP: Transition = { type: 'spring', stiffness: 600, damping: 34 };
export const EASE: Transition = { duration: 0.22, ease: [0.16, 1, 0.3, 1] };

/** Reduced-motion replacement: state changes, nothing travels. */
const FADE: Variants = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { duration: 0.15 } },
  exit: { opacity: 0, transition: { duration: 0.1 } },
};

/**
 * Stagger for lists — queue rows, stat tiles.
 *
 * 40 ms per child. Fast enough that eight rows are fully in before anyone could read
 * the first, slow enough that the eye registers order rather than a single flash.
 */
export function listContainer(reduced: boolean, stagger = 0.04): Variants {
  if (reduced) return { hidden: {}, show: {} };
  return {
    hidden: {},
    show: { transition: { staggerChildren: stagger, delayChildren: 0.02 } },
  };
}

export function listItem(reduced: boolean): Variants {
  if (reduced) return FADE;
  return {
    hidden: { opacity: 0, y: 8 },
    show: { opacity: 1, y: 0, transition: SPRING },
    exit: { opacity: 0, y: -4, transition: { duration: 0.12 } },
  };
}

/** Panels arriving on a view change. */
export function panelIn(reduced: boolean): Variants {
  if (reduced) return FADE;
  return {
    hidden: { opacity: 0, y: 12 },
    show: { opacity: 1, y: 0, transition: SPRING_SOFT },
    exit: { opacity: 0, transition: { duration: 0.12 } },
  };
}

/**
 * The glass drawer.
 *
 * Slides from the right on a soft spring so it decelerates into place rather than
 * stopping dead — the one place in this interface where depth is the point.
 */
export function drawer(reduced: boolean): Variants {
  if (reduced) return FADE;
  return {
    hidden: { opacity: 0, x: 32 },
    show: { opacity: 1, x: 0, transition: SPRING_SOFT },
    exit: { opacity: 0, x: 24, transition: { duration: 0.14 } },
  };
}

/**
 * Press feedback for controls that are not plain `.nb-btn`.
 *
 * The scale is deliberately tiny. The shadow collapse in CSS does the visible work;
 * this just adds the weight behind it.
 */
export function press(reduced: boolean) {
  if (reduced) return {};
  return { whileTap: { scale: 0.97 }, transition: SPRING_SNAP };
}

/** A node or badge arriving with weight — used when the ring assembles. */
export function pop(reduced: boolean): Variants {
  if (reduced) return FADE;
  return {
    hidden: { opacity: 0, scale: 0.6 },
    show: { opacity: 1, scale: 1, transition: SPRING },
  };
}

/**
 * Count a number up when it first appears or changes.
 *
 * Rounded to the caller's precision on every frame rather than at the end, so the
 * digits settle instead of snapping. Reduced motion returns the value immediately —
 * a rolling number is exactly the kind of movement that provokes discomfort.
 *
 * Driven by `requestAnimationFrame` rather than a spring, because the thing being
 * animated is a scalar the user reads, not an object they can see move.
 */
export function useCountUp(value: number, durationMs = 700): number {
  const reduced = useReducedMotion();
  const [display, setDisplay] = useState(value);
  const from = useRef(value);
  const frame = useRef<number | null>(null);

  useEffect(() => {
    if (reduced || !Number.isFinite(value)) {
      setDisplay(value);
      from.current = value;
      return;
    }

    const start = performance.now();
    const origin = from.current;
    const delta = value - origin;

    if (delta === 0) return;

    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / durationMs);
      // Ease-out cubic: fast to begin, settling at the end, which is how a counter
      // reads as "arriving at" a figure rather than sliding past it.
      const eased = 1 - Math.pow(1 - t, 3);
      setDisplay(origin + delta * eased);
      if (t < 1) {
        frame.current = requestAnimationFrame(tick);
      } else {
        from.current = value;
      }
    };

    frame.current = requestAnimationFrame(tick);
    return () => {
      if (frame.current) cancelAnimationFrame(frame.current);
      from.current = value;
    };
  }, [value, durationMs, reduced]);

  return display;
}

/** Re-export so components need one import for motion decisions. */
export { useReducedMotion };
