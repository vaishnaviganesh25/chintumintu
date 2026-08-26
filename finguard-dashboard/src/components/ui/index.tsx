import { motion, AnimatePresence } from 'framer-motion';
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from 'react';
import { Icon, type IconName } from '../Icon';
import {
  drawer as drawerVariants,
  listContainer,
  listItem,
  panelIn,
  useCountUp,
  useReducedMotion,
} from '../../motion';

/**
 * The primitives every view is built from.
 *
 * These exist so the neobrutalist decisions live in one place. When a border weight or
 * a shadow offset is wrong it is wrong once, not in eleven components — and it is the
 * only way the "no component names a colour" rule survives contact with a deadline.
 */

/* -------------------------------------------------------------------------- */
/* Panel                                                                       */
/* -------------------------------------------------------------------------- */
export function Panel({
  children,
  title,
  subtitle,
  action,
  flat,
  className = '',
  padded = true,
}: {
  children: ReactNode;
  title?: string;
  subtitle?: string;
  action?: ReactNode;
  /** Drop the offset shadow. Used where panels tile and the shadows would collide. */
  flat?: boolean;
  className?: string;
  padded?: boolean;
}) {
  const reduced = useReducedMotion();

  return (
    <motion.section
      variants={panelIn(!!reduced)}
      initial="hidden"
      animate="show"
      className={`${flat ? 'nb-panel-flat' : 'nb-panel'} ${className}`}
    >
      {(title || action) && (
        <header
          className="flex items-start justify-between gap-3"
          style={{
            padding: '14px 18px',
            borderBottom: 'var(--border)',
          }}
        >
          <div className="min-w-0">
            {title && (
              <h2 className="nb-display" style={{ fontSize: 15 }}>
                {title}
              </h2>
            )}
            {subtitle && (
              <p style={{ fontSize: 12, color: 'var(--muted)', marginTop: 1 }}>{subtitle}</p>
            )}
          </div>
          {action}
        </header>
      )}
      <div style={padded ? { padding: 18 } : undefined}>{children}</div>
    </motion.section>
  );
}

/* -------------------------------------------------------------------------- */
/* Button                                                                      */
/* -------------------------------------------------------------------------- */
type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'default' | 'primary' | 'danger';
  icon?: IconName;
  children?: ReactNode;
};

/**
 * The press is handled entirely in CSS — the control translates into its own shadow.
 * Doing it there rather than in Framer means it works on every button including ones
 * that never mount through React, and it degrades with `prefers-reduced-motion` for
 * free.
 */
export function Button({ variant = 'default', icon, children, className = '', ...rest }: ButtonProps) {
  const variantClass =
    variant === 'primary' ? 'nb-btn-primary' : variant === 'danger' ? 'nb-btn-danger' : '';

  return (
    <button type="button" className={`nb-btn ${variantClass} ${className}`} {...rest}>
      {icon && <Icon name={icon} size={15} />}
      {children}
    </button>
  );
}

/* -------------------------------------------------------------------------- */
/* Badge                                                                       */
/* -------------------------------------------------------------------------- */
export function Badge({
  children,
  tone = 'neutral',
  dot,
}: {
  children: ReactNode;
  tone?: 'neutral' | 'accept' | 'challenge' | 'hold' | 'accent';
  dot?: boolean;
}) {
  // Fills, not text colours — a badge is a block with ink on it, so the vivid half of
  // each semantic pair is the right one and only needs 3:1.
  const fill = {
    neutral: 'var(--sunk)',
    accept: 'var(--accept-fill)',
    challenge: 'var(--challenge-fill)',
    hold: 'var(--hold-fill)',
    accent: 'var(--accent)',
  }[tone];

  return (
    <span
      className="nb-badge"
      style={{
        background: fill,
        color: tone === 'accent' ? 'var(--accent-ink)' : tone === 'neutral' ? 'var(--ink)' : '#0b0b0b',
      }}
    >
      {dot && (
        <span
          style={{ width: 5, height: 5, borderRadius: 999, background: 'currentColor' }}
        />
      )}
      {children}
    </span>
  );
}

/* -------------------------------------------------------------------------- */
/* Stat                                                                        */
/* -------------------------------------------------------------------------- */
export function Stat({
  label,
  value,
  hint,
  format,
  tone,
}: {
  label: string;
  /** Numeric values count up; a string is shown as-is (for em-dashes and "n/a"). */
  value: number | string;
  hint?: string;
  format?: (n: number) => string;
  tone?: 'accept' | 'challenge' | 'hold';
}) {
  const numeric = typeof value === 'number' ? value : 0;
  const counted = useCountUp(numeric);
  const shown =
    typeof value === 'string'
      ? value
      : format
        ? format(counted)
        : Math.round(counted).toLocaleString('en-IN');

  const accentColour = tone ? `var(--${tone})` : undefined;

  return (
    <div className="nb-panel nb-hatch" style={{ padding: '13px 15px' }}>
      <p className="nb-label">{label}</p>
      <p
        className="nb-display"
        style={{ fontSize: 26, lineHeight: 1.1, marginTop: 3, color: accentColour }}
      >
        {shown}
      </p>
      {hint && (
        <p style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>{hint}</p>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Skeleton                                                                    */
/* -------------------------------------------------------------------------- */
/**
 * Structure before content. A block of roughly the right shape reads as "loading"
 * far faster than a spinner reads as anything, and it stops the layout jumping when
 * the data lands.
 */
export function Skeleton({ height = 16, width = '100%' }: { height?: number; width?: number | string }) {
  return <div className="nb-skeleton" style={{ height, width }} aria-hidden="true" />;
}

export function SkeletonRows({ rows = 5, height = 46 }: { rows?: number; height?: number }) {
  return (
    <div className="flex flex-col gap-2" role="status" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} height={height} />
      ))}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Field                                                                       */
/* -------------------------------------------------------------------------- */
export function Field({
  label,
  hint,
  error,
  optional,
  id,
  ...rest
}: InputHTMLAttributes<HTMLInputElement> & {
  label: string;
  hint?: string;
  error?: string;
  optional?: boolean;
  id: string;
}) {
  return (
    <div>
      <label className="nb-label block" style={{ marginBottom: 5 }} htmlFor={id}>
        {label}
        {optional && <span style={{ color: 'var(--faint)' }}> · optional</span>}
      </label>
      <input
        id={id}
        className="nb-input"
        aria-describedby={error ? `${id}-error` : hint ? `${id}-hint` : undefined}
        aria-invalid={error ? true : undefined}
        style={error ? { borderColor: 'var(--hold)' } : undefined}
        {...rest}
      />
      {error ? (
        <p
          id={`${id}-error`}
          role="alert"
          style={{ fontSize: 11.5, color: 'var(--hold)', marginTop: 4 }}
        >
          {error}
        </p>
      ) : hint ? (
        <p id={`${id}-hint`} style={{ fontSize: 11.5, color: 'var(--muted)', marginTop: 4 }}>
          {hint}
        </p>
      ) : null}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Drawer                                                                      */
/* -------------------------------------------------------------------------- */
/**
 * The one place glass earns its keep: a case file floating over the queue it came
 * from, with the queue still legible behind it. Everywhere else in this interface,
 * surfaces are solid.
 */
export function Drawer({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
}) {
  const reduced = useReducedMotion();

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.16 }}
            onClick={onClose}
            style={{
              position: 'fixed',
              inset: 0,
              background: 'color-mix(in srgb, var(--ink) 26%, transparent)',
              zIndex: 40,
            }}
          />
          <motion.aside
            variants={drawerVariants(!!reduced)}
            initial="hidden"
            animate="show"
            exit="exit"
            role="dialog"
            aria-modal="true"
            aria-label={title}
            className="nb-glass"
            style={{
              position: 'fixed',
              top: 0,
              right: 0,
              bottom: 0,
              width: 'min(560px, 100vw)',
              zIndex: 50,
              overflowY: 'auto',
              borderRadius: 0,
              borderRight: 'none',
              boxShadow: 'var(--shadow-hard-lg)',
            }}
          >
            <header
              className="flex items-center justify-between gap-3 sticky top-0 nb-glass"
              style={{ padding: '13px 18px', borderBottom: 'var(--border)', borderTop: 'none', borderLeft: 'none', borderRight: 'none', zIndex: 1 }}
            >
              <h2 className="nb-display" style={{ fontSize: 15 }}>
                {title}
              </h2>
              <Button icon="chevron-right" onClick={onClose} aria-label="Close">
                Close
              </Button>
            </header>
            <div style={{ padding: 18 }}>{children}</div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}

/* -------------------------------------------------------------------------- */
/* Staggered list                                                              */
/* -------------------------------------------------------------------------- */
export function StaggerList({ children, className = '' }: { children: ReactNode; className?: string }) {
  const reduced = useReducedMotion();
  return (
    <motion.div
      variants={listContainer(!!reduced)}
      initial="hidden"
      animate="show"
      className={className}
    >
      {children}
    </motion.div>
  );
}

export function StaggerItem({ children, className = '', ...rest }: { children: ReactNode; className?: string; [k: string]: unknown }) {
  const reduced = useReducedMotion();
  return (
    <motion.div variants={listItem(!!reduced)} className={className} {...rest}>
      {children}
    </motion.div>
  );
}

/* -------------------------------------------------------------------------- */
/* Empty / error states                                                        */
/* -------------------------------------------------------------------------- */
export function Notice({
  tone = 'neutral',
  icon,
  children,
}: {
  tone?: 'neutral' | 'hold' | 'challenge';
  icon?: IconName;
  children: ReactNode;
}) {
  const colour = tone === 'neutral' ? 'var(--muted)' : `var(--${tone})`;
  const bg = tone === 'neutral' ? 'var(--sunk)' : `var(--${tone}-soft)`;

  return (
    <div
      role={tone === 'hold' ? 'alert' : undefined}
      className="flex items-start gap-2.5"
      style={{
        background: bg,
        border: 'var(--border-w) solid ' + colour,
        borderRadius: 'var(--radius-sm)',
        padding: '10px 13px',
        fontSize: 12.5,
        color: 'var(--ink)',
      }}
    >
      {icon && (
        <span style={{ color: colour, flexShrink: 0, marginTop: 1 }}>
          <Icon name={icon} size={15} />
        </span>
      )}
      <div>{children}</div>
    </div>
  );
}
