import type { SVGProps } from 'react';

/**
 * The icon set.
 *
 * Hand-drawn on a 24-unit grid with a 2px stroke, round caps and round joins, so every
 * glyph shares a weight and a rhythm — and so they sit beside 2px brutalist borders
 * without looking spindly next to them. Consistency is the whole reason this is one file
 * rather than icons pasted in as needed — a set assembled from three libraries reads as
 * three sets, and that is one of the things that makes an interface look thrown
 * together.
 *
 * Emoji are not used anywhere in this product. They render differently on every
 * platform, carry no stroke weight to match, and cannot inherit a colour token.
 */

export type IconName =
  | 'shield'
  | 'flask'
  | 'inbox'
  | 'network'
  | 'file-text'
  | 'activity'
  | 'database'
  | 'check'
  | 'pause'
  | 'alert'
  | 'clock'
  | 'chevron-right'
  | 'sun'
  | 'moon'
  | 'monitor'
  | 'power'
  | 'arrow-right'
  | 'external';

interface IconProps extends Omit<SVGProps<SVGSVGElement>, 'name'> {
  name: IconName;
  size?: number;
  /** Screen-reader label. Omit for decorative icons sitting beside real text. */
  title?: string;
}

/** Path data only — every glyph inherits stroke, colour and sizing from the wrapper. */
const PATHS: Record<IconName, React.ReactNode> = {
  // A shield with a notch, not a tick — the product assesses risk, it does not bless.
  shield: <path d="M12 3.2 5 6v5.4c0 4.2 2.9 7.5 7 9.4 4.1-1.9 7-5.2 7-9.4V6l-7-2.8Z" />,
  flask: (
    <>
      <path d="M9.5 3.5h5M10.5 3.5v5.2L5.9 17a2.2 2.2 0 0 0 1.9 3.4h8.4a2.2 2.2 0 0 0 1.9-3.4l-4.6-8.3V3.5" />
      <path d="M7.6 14.2h8.8" />
    </>
  ),
  inbox: (
    <>
      <path d="M3.5 12.8h4.2l1.5 2.6h5.6l1.5-2.6h4.2" />
      <path d="M6.2 4.4h11.6l2.7 8.4v4.6a2 2 0 0 1-2 2H5.5a2 2 0 0 1-2-2v-4.6l2.7-8.4Z" />
    </>
  ),
  // Three payers converging on one account — the mule ring, as a mark.
  network: (
    <>
      <circle cx="12" cy="17.5" r="2.6" />
      <circle cx="5" cy="6.5" r="2.2" />
      <circle cx="12" cy="4.6" r="2.2" />
      <circle cx="19" cy="6.5" r="2.2" />
      <path d="M6.2 8.4 10.6 15.3M12 6.8v8.1M17.8 8.4 13.4 15.3" />
    </>
  ),
  'file-text': (
    <>
      <path d="M13.6 3.5H7a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8.9l-5.4-5.4Z" />
      <path d="M13.4 3.6v5.2h5.3M8.6 13h6.8M8.6 16.6h4.8" />
    </>
  ),
  activity: <path d="M3.5 12h3.7l2.6-6.8 3.9 13.6 2.6-6.8h4.2" />,
  database: (
    <>
      <ellipse cx="12" cy="6.2" rx="7.2" ry="2.9" />
      <path d="M4.8 6.2v11.6c0 1.6 3.2 2.9 7.2 2.9s7.2-1.3 7.2-2.9V6.2" />
      <path d="M4.8 12c0 1.6 3.2 2.9 7.2 2.9s7.2-1.3 7.2-2.9" />
    </>
  ),
  check: (
    <>
      <circle cx="12" cy="12" r="8.4" />
      <path d="M8.6 12.2l2.4 2.4 4.6-4.9" />
    </>
  ),
  pause: (
    <>
      <circle cx="12" cy="12" r="8.4" />
      <path d="M10.2 9.4v5.2M13.8 9.4v5.2" />
    </>
  ),
  alert: (
    <>
      <path d="M10.3 4.2 2.9 17.1a2 2 0 0 0 1.7 3h14.8a2 2 0 0 0 1.7-3L13.7 4.2a2 2 0 0 0-3.4 0Z" />
      <path d="M12 9.4v4M12 16.6h.01" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="8.4" />
      <path d="M12 7.4V12l3 1.8" />
    </>
  ),
  'chevron-right': <path d="M9.6 5.4 16 12l-6.4 6.6" />,
  sun: (
    <>
      <circle cx="12" cy="12" r="3.8" />
      <path d="M12 2.6v2.2M12 19.2v2.2M4.3 4.3l1.6 1.6M18.1 18.1l1.6 1.6M2.6 12h2.2M19.2 12h2.2M4.3 19.7l1.6-1.6M18.1 5.9l1.6-1.6" />
    </>
  ),
  moon: <path d="M20 13.4A8.4 8.4 0 0 1 10.6 4a8.4 8.4 0 1 0 9.4 9.4Z" />,
  monitor: (
    <>
      <rect x="3" y="4.4" width="18" height="12" rx="2" />
      <path d="M8.6 20.2h6.8M12 16.4v3.8" />
    </>
  ),
  power: (
    <>
      <path d="M12 3.4v8.2" />
      <path d="M17.7 6.6a8 8 0 1 1-11.4 0" />
    </>
  ),
  'arrow-right': <path d="M4.6 12h14M13.4 6.6 18.8 12l-5.4 5.4" />,
  external: (
    <>
      <path d="M14.4 4.4H19.6v5.2" />
      <path d="M12.2 11.8 19.6 4.4" />
      <path d="M18 14v4.6a1.8 1.8 0 0 1-1.8 1.8H5.8A1.8 1.8 0 0 1 4 18.6V8.2a1.8 1.8 0 0 1 1.8-1.8H10" />
    </>
  ),
};

export function Icon({ name, size = 18, title, ...rest }: IconProps) {
  const glyph = PATHS[name];

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
      // Decorative unless given a title. Announcing every icon beside its own label
      // makes a screen reader read the interface twice.
      aria-hidden={title ? undefined : true}
      role={title ? 'img' : undefined}
      focusable="false"
      {...rest}
    >
      {title && <title>{title}</title>}
      {glyph}
    </svg>
  );
}
