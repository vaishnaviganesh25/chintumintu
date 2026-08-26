import type { SVGProps } from 'react';

/**
 * Brand and payment-method marks.
 *
 * **These are drawn, not copied.** Trademark guidance for referring to someone else's
 * product is to use as much of the mark as is necessary and no more — "the words but
 * not the font or symbol". So there is no Visa, Mastercard, UPI or RuPay artwork here.
 * Each method gets a glyph of our own on the same 24-unit grid and 2px stroke as every
 * other icon, and the method is named in text beside it.
 *
 * That constraint and good design point the same way. Scraped brand SVGs never share a
 * stroke weight, an optical size, or a corner radius, so a row of them always looks
 * assembled rather than designed. A hand-built set is the only way this reads as one
 * product.
 */

export type MethodName = 'upi' | 'card' | 'netbanking' | 'wallet';

interface MarkProps extends SVGProps<SVGSVGElement> {
  size?: number;
}

const METHOD_PATHS: Record<MethodName, React.ReactNode> = {
  // A phone with a rupee glyph — UPI is a mobile-first rail, so the device is the
  // honest signifier rather than any particular app's colours.
  upi: (
    <>
      <rect x="6" y="2.6" width="12" height="18.8" rx="2.4" />
      <path d="M9.6 8.2h4.8M9.6 11h4.8M13.4 8.2c1.1 0 1.9.6 1.9 1.4s-.8 1.4-1.9 1.4h-2.2l3.4 3.4" />
    </>
  ),
  // A card with a magnetic stripe and a chip.
  card: (
    <>
      <rect x="2.4" y="5.2" width="19.2" height="13.6" rx="2.2" />
      <path d="M2.4 9.6h19.2" />
      <rect x="5.4" y="12.6" width="4" height="3" rx="0.6" />
    </>
  ),
  // A bank facade — columns and a pediment.
  netbanking: (
    <>
      <path d="M3.2 9.4 12 4.2l8.8 5.2" />
      <path d="M5.4 9.4v8.2M9.8 9.4v8.2M14.2 9.4v8.2M18.6 9.4v8.2" />
      <path d="M3 20.4h18" />
    </>
  ),
  // A purse with a clasp.
  wallet: (
    <>
      <path d="M3.4 7.6h14.2a2.6 2.6 0 0 1 2.6 2.6v6.8a2.6 2.6 0 0 1-2.6 2.6H5.4a2 2 0 0 1-2-2V7.6Z" />
      <path d="M3.4 7.6V6a1.8 1.8 0 0 1 1.8-1.8h10.4" />
      <circle cx="16.6" cy="13.6" r="1.3" />
    </>
  ),
};

export const METHOD_LABEL: Record<MethodName, string> = {
  upi: 'UPI',
  card: 'Card',
  netbanking: 'Netbanking',
  wallet: 'Wallet',
};

export function PaymentMark({ method, size = 18, ...rest }: MarkProps & { method: MethodName }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {METHOD_PATHS[method]}
    </svg>
  );
}

/** Glyph plus the method named in text — the form the trademark guidance points to. */
export function MethodTag({ method }: { method: MethodName }) {
  return (
    <span
      className="nb-mono inline-flex items-center gap-1.5"
      style={{ fontSize: 11, fontWeight: 700, color: 'var(--muted)' }}
    >
      <PaymentMark method={method} size={14} />
      {METHOD_LABEL[method]}
    </span>
  );
}

/* -------------------------------------------------------------------------- */
/* FinGuard mark                                                               */
/* -------------------------------------------------------------------------- */
/**
 * The product mark: a shield with three payers converging on one account inside it.
 *
 * The ring is the thing this product is actually about, so it belongs in the mark
 * rather than a generic padlock. Drawn at brutalist weight to sit beside 2px borders
 * without looking spindly.
 */
export function Logomark({ size = 26, ...rest }: MarkProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      <path
        d="M16 2.6 4.6 7.4v9.1c0 7 4.9 12.3 11.4 14.9 6.5-2.6 11.4-7.9 11.4-14.9V7.4L16 2.6Z"
        fill="var(--accent)"
        stroke="currentColor"
        strokeWidth={2.2}
        strokeLinejoin="round"
      />
      <path
        d="M10.4 11.6 15 17.6M16 10.2v7.4M21.6 11.6 17 17.6"
        stroke="var(--accent-ink)"
        strokeWidth={1.8}
        strokeLinecap="round"
      />
      <circle cx="16" cy="20.4" r="2.6" fill="var(--accent-ink)" />
      <circle cx="9.4" cy="10.2" r="1.7" fill="var(--accent-ink)" />
      <circle cx="16" cy="8.6" r="1.7" fill="var(--accent-ink)" />
      <circle cx="22.6" cy="10.2" r="1.7" fill="var(--accent-ink)" />
    </svg>
  );
}

export function Logotype({ compact = false }: { compact?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2.5" style={{ color: 'var(--ink)' }}>
      <Logomark size={compact ? 22 : 26} />
      {!compact && (
        <span
          className="nb-display"
          style={{ fontSize: 19, letterSpacing: '-0.035em', lineHeight: 1 }}
        >
          FinGuard
        </span>
      )}
    </span>
  );
}
