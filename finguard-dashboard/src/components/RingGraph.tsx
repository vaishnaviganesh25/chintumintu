import { useEffect, useMemo, useRef, useState } from 'react';
import { Icon } from './Icon';
import type { RingDetail, RingSummary } from '../types';
import { fetchRing, fetchRings, isAbortError } from '../services/opsApi';

/**
 * A mule ring, drawn as the star it is.
 *
 * The layout is radial and deterministic rather than a force simulation. Every
 * incident in this data is a true star — several victims, one collecting account — so
 * a force layout would spend its time jittering toward an arrangement we can compute
 * exactly, and land somewhere slightly different each run. Exactness is worth more
 * than the animation of a solver settling.
 *
 * What is animated is the thing that matters: the transfers arrive in the order they
 * happened. The point is not that the ring exists — it is that the ring *assembles*,
 * and that the hub only becomes visible on the transfer where the third distinct
 * victim appears. That is the same backward-looking signal the model sees, drawn.
 */

const SIZE = 460;
const CENTRE = SIZE / 2;
const RADIUS = 158;
const HUB_FANIN = 3;

const rupees = (v: number) => `₹${v.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;

function shortVpa(vpa: string) {
  const [local, handle] = vpa.split('@');
  return local.length > 14 ? `${local.slice(0, 13)}…@${handle}` : vpa;
}

interface Placed {
  vpa: string;
  x: number;
  y: number;
}

/** Victims evenly around the circle, starting at the top so the layout reads upright. */
function placeSenders(senders: string[]): Placed[] {
  return senders.map((vpa, i) => {
    const angle = (i / senders.length) * Math.PI * 2 - Math.PI / 2;
    return {
      vpa,
      x: CENTRE + Math.cos(angle) * RADIUS,
      y: CENTRE + Math.sin(angle) * RADIUS,
    };
  });
}

function RingCanvas({ ring, step }: { ring: RingDetail; step: number }) {
  const placed = useMemo(() => placeSenders(ring.senders), [ring.senders]);
  const byVpa = useMemo(
    () => new Map(placed.map((p) => [p.vpa, p])),
    [placed],
  );

  const visible = ring.edges.slice(0, step);
  const maxAmount = Math.max(...ring.edges.map((e) => e.amount), 1);

  // Fan-in as of the transfers drawn so far, which is exactly what the model would
  // have known at that moment.
  const seen = new Set(visible.map((e) => e.sender));
  const fanin = seen.size;
  const isHub = fanin >= HUB_FANIN;
  const collected = visible.reduce((sum, e) => sum + e.amount, 0);

  const muleColour = isHub ? 'var(--node-mule)' : 'var(--muted)';

  return (
    <div className="flex flex-col items-center gap-3">
      <svg
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        style={{ width: '100%', maxWidth: SIZE, height: 'auto' }}
        role="img"
        aria-label={
          `Payment ring: ${fanin} distinct payer${fanin === 1 ? '' : 's'} into ` +
          `${ring.receivers[0]}, ${rupees(collected)} collected so far` +
          (isHub ? '. Fan-in threshold reached.' : '.')
        }
      >
        {/* Edges first, so nodes sit on top of them. */}
        {visible.map((edge, i) => {
          const from = byVpa.get(edge.sender);
          if (!from) return null;
          const newest = i === visible.length - 1;
          return (
            <line
              key={`${edge.sender}-${edge.timestamp}-${i}`}
              x1={from.x}
              y1={from.y}
              x2={CENTRE}
              y2={CENTRE}
              stroke={newest ? muleColour : 'var(--edge)'}
              strokeWidth={1 + (edge.amount / maxAmount) * 3.5}
              strokeLinecap="round"
              opacity={newest ? 0.95 : 0.55}
            />
          );
        })}

        {/* The collecting account. It grows with what it has taken, which is the
            visual the whole thing exists to deliver. */}
        <circle
          cx={CENTRE}
          cy={CENTRE}
          r={26 + Math.min(fanin, 5) * 3.5}
          fill={isHub ? 'var(--hold-soft)' : 'var(--sunk)'}
          stroke={muleColour}
          strokeWidth={isHub ? 2.4 : 1.6}
          style={{ transition: 'all 260ms ease' }}
        />
        <text
          x={CENTRE}
          y={CENTRE - 2}
          textAnchor="middle"
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 15,
            fontWeight: 600,
            fill: muleColour,
          }}
        >
          {fanin}
        </text>
        <text
          x={CENTRE}
          y={CENTRE + 12}
          textAnchor="middle"
          style={{ fontFamily: 'var(--font-mono)', fontSize: 8.5, fill: 'var(--faint)' }}
        >
          FAN-IN
        </text>

        {/* Victims. Dim until they have actually paid. */}
        {placed.map((p) => {
          const paid = seen.has(p.vpa);
          return (
            <g key={p.vpa} style={{ transition: 'opacity 200ms ease' }} opacity={paid ? 1 : 0.28}>
              <circle
                cx={p.x}
                cy={p.y}
                r={13}
                fill="var(--surface)"
                stroke={paid ? 'var(--node-victim)' : 'var(--rule-strong)'}
                strokeWidth={1.6}
              />
              <text
                x={p.x}
                y={p.y + 3.5}
                textAnchor="middle"
                style={{ fontFamily: 'var(--font-mono)', fontSize: 9, fill: 'var(--muted)' }}
              >
                {p.vpa.slice(0, 2).toUpperCase()}
              </text>
              <text
                x={p.x}
                y={p.y + (p.y < CENTRE ? -20 : 30)}
                textAnchor="middle"
                style={{ fontFamily: 'var(--font-mono)', fontSize: 9.5, fill: 'var(--faint)' }}
              >
                {shortVpa(p.vpa)}
              </text>
            </g>
          );
        })}
      </svg>

      <p
        className="fg-mono text-center"
        style={{ fontSize: 12, color: isHub ? 'var(--hold)' : 'var(--muted)' }}
        aria-live="polite"
      >
        {isHub
          ? `Fan-in ${fanin} — hub threshold reached, ${rupees(collected)} collected`
          : `Fan-in ${fanin} — ${rupees(collected)} collected, nothing unusual yet`}
      </p>
    </div>
  );
}

export function RingGraph() {
  const [summaries, setSummaries] = useState<RingSummary[]>([]);
  const [ring, setRing] = useState<RingDetail | null>(null);
  const [step, setStep] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchRings(30, controller.signal)
      .then((rows) => {
        setSummaries(rows);
        if (rows.length) void open(rows[0].ring_id);
      })
      .catch((err) => {
        if (isAbortError(err)) return;
        setError(err instanceof Error ? err.message : 'Could not load incidents.');
      });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const open = async (ringId: string) => {
    setError(null);
    setPlaying(false);
    try {
      const detail = await fetchRing(ringId);
      setRing(detail);
      // Reduced motion gets the finished ring rather than no ring at all — the
      // information is the point, the animation is how it is delivered.
      const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
      setStep(reduced ? detail.edges.length : 0);
      setPlaying(!reduced);
    } catch (err) {
      if (isAbortError(err)) return;
      setError(err instanceof Error ? err.message : 'Could not load that incident.');
    }
  };

  useEffect(() => {
    if (!playing || !ring) return;
    if (step >= ring.edges.length) {
      setPlaying(false);
      return;
    }
    timer.current = window.setTimeout(() => setStep((s) => s + 1), 850);
    return () => {
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, [playing, step, ring]);

  const replay = () => {
    setStep(0);
    setPlaying(true);
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[300px_1fr] gap-5">
      {/* Incident list -------------------------------------------------- */}
      <section className="fg-surface" style={{ padding: 0, overflow: 'hidden' }}>
        <header className="px-4 py-3" style={{ borderBottom: '1px solid var(--rule)' }}>
          <h2 style={{ fontSize: 13, fontWeight: 600 }}>Incidents</h2>
          <p style={{ fontSize: 11.5, color: 'var(--muted)' }}>
            Highest fan-in first
          </p>
        </header>

        {error && (
          <p className="px-4 py-3" style={{ fontSize: 12, color: 'var(--hold)' }} role="alert">
            {error}
          </p>
        )}

        <ul style={{ maxHeight: 520, overflowY: 'auto' }}>
          {summaries.map((s) => {
            const selected = ring?.ring_id === s.ring_id;
            return (
              <li key={s.ring_id} style={{ borderBottom: '1px solid var(--rule)' }}>
                <button
                  type="button"
                  onClick={() => void open(s.ring_id)}
                  aria-current={selected ? 'true' : undefined}
                  className="w-full text-left px-4 py-2.5"
                  style={{
                    background: selected ? 'var(--accent-soft)' : 'transparent',
                    border: 'none',
                    cursor: 'pointer',
                  }}
                >
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="fg-mono" style={{ fontSize: 12, color: 'var(--ink)' }}>
                      {s.ring_id.replace('ring_', '')}
                    </span>
                    <span
                      className="fg-mono"
                      style={{ fontSize: 11, color: 'var(--hold)' }}
                    >
                      {s.fanin} payers
                    </span>
                  </div>
                  <p className="fg-mono" style={{ fontSize: 11, color: 'var(--muted)' }}>
                    {rupees(s.total_amount)} in {s.window_seconds}s
                  </p>
                </button>
              </li>
            );
          })}
        </ul>
      </section>

      {/* The star ------------------------------------------------------- */}
      <section className="fg-surface" style={{ padding: 20 }}>
        {!ring ? (
          <p style={{ fontSize: 13, color: 'var(--muted)', textAlign: 'center', padding: '80px 0' }}>
            Select an incident to replay it.
          </p>
        ) : (
          <>
            <header className="flex flex-wrap items-start justify-between gap-3 mb-4">
              <div>
                <h2 style={{ fontSize: 14, fontWeight: 600 }}>
                  {ring.pattern.replace(/_/g, ' ')}
                </h2>
                <p className="fg-mono" style={{ fontSize: 11.5, color: 'var(--muted)' }}>
                  {ring.receivers[0]} · receiver {ring.receiver_age_days} days old ·{' '}
                  {rupees(ring.total_amount)} over {ring.window_seconds}s
                </p>
              </div>

              <div className="flex gap-2">
                <button type="button" className="fg-btn" onClick={replay}>
                  <Icon name="activity" size={14} />
                  Replay
                </button>
                <button
                  type="button"
                  className="fg-btn"
                  onClick={() => setStep(ring.edges.length)}
                  disabled={step >= ring.edges.length}
                >
                  Show all
                </button>
              </div>
            </header>

            <RingCanvas ring={ring} step={step} />

            {/* The transfer log, so the animation has something exact behind it. */}
            <ol className="mt-5" style={{ borderTop: '1px solid var(--rule)' }}>
              {ring.edges.map((edge, i) => {
                const shown = i < step;
                return (
                  <li
                    key={`${edge.sender}-${i}`}
                    className="flex items-baseline justify-between gap-3 py-1.5"
                    style={{
                      borderBottom: '1px solid var(--rule)',
                      opacity: shown ? 1 : 0.32,
                      fontSize: 12,
                    }}
                  >
                    <span className="fg-mono" style={{ color: 'var(--faint)', width: 52 }}>
                      +{edge.offset_seconds}s
                    </span>
                    <span className="fg-mono truncate flex-1" style={{ color: 'var(--muted)' }}>
                      {edge.sender}
                    </span>
                    <Icon name="arrow-right" size={13} />
                    <span className="fg-mono" style={{ color: 'var(--ink)' }}>
                      {rupees(edge.amount)}
                    </span>
                  </li>
                );
              })}
            </ol>

            <p style={{ fontSize: 11.5, color: 'var(--muted)', marginTop: 14, maxWidth: '62ch' }}>
              Fan-in is counted over a trailing ten-minute window, closed at the current
              payment. The first transfer into this account genuinely looked ordinary —
              the hub only becomes visible on the transfer where the third distinct payer
              appears. The model is not being shown the future; it is watching the star form.
            </p>
          </>
        )}
      </section>
    </div>
  );
}
