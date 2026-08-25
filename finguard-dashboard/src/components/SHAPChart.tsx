import {
  Bar,
  BarChart,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { SHAPFeature } from '../types';

interface SHAPChartProps {
  features: SHAPFeature[];
}

/** Enough to show the story without turning the panel into a wall of bars. */
const MAX_BARS = 8;
const LABEL_LIMIT = 30;

/**
 * The diverging pair, read from the theme rather than hardcoded.
 *
 * Recharts needs concrete colour strings, not CSS variables, so the tokens are
 * resolved off the document at render time. Re-tuned per theme: the light palette's
 * brick red is unreadable on a near-black ground, and the dark palette's coral is
 * washed out on white. Reusing one pair across both is how a chart ends up illegible
 * in whichever theme it was not designed in.
 */
function themeColour(token: string, fallback: string): string {
  if (typeof window === 'undefined') return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(token).trim();
  return value || fallback;
}

/**
 * Diverging bar chart of per-concept SHAP contributions.
 *
 * SHAP values are signed and additive, not shares of a whole: a value of -0.21 means
 * that concept argued *against* the fraud verdict. Rendering them on a 0-100% scale
 * would hide every mitigating factor and misrepresent the rest, so the axis is
 * symmetric around zero and direction is carried by colour.
 */
export function SHAPChart({ features }: SHAPChartProps) {
  const riskColour = themeColour('--shap-risk', '#a32723');
  const safeColour = themeColour('--shap-safe', '#0e6e4e');

  if (features.length === 0) {
    return (
      <div className="flex items-center justify-center h-64" style={{ color: 'var(--muted)' }}>
        No feature data available
      </div>
    );
  }

  const chartData = [...features]
    .sort((a, b) => Math.abs(b.importance) - Math.abs(a.importance))
    .slice(0, MAX_BARS)
    .map((feature) => ({
      name: feature.feature,
      label:
        feature.feature.length > LABEL_LIMIT
          ? `${feature.feature.slice(0, LABEL_LIMIT - 1)}…`
          : feature.feature,
      importance: feature.importance,
    }));

  // A symmetric domain keeps a +0.30 bar and a -0.30 bar the same length, so the
  // eye compares magnitudes correctly across the zero line.
  const maxAbs = Math.max(...chartData.map((d) => Math.abs(d.importance)), 0.01);
  const bound = maxAbs * 1.15;

  const chartHeight = Math.max(240, chartData.length * 34 + 48);

  const customTooltip = ({ active, payload }: any) => {
    if (!active || !payload?.length) return null;
    const { name, importance } = payload[0].payload;
    const towardsFraud = importance > 0;
    return (
      <div className="fg-surface p-3 max-w-xs" style={{ boxShadow: 'var(--shadow-md)' }}>
        <p className="text-[13px] font-medium">{name}</p>
        <p
          className="fg-mono font-semibold"
          style={{ color: towardsFraud ? riskColour : safeColour }}
        >
          {importance > 0 ? '+' : ''}
          {importance.toFixed(4)}
        </p>
        <p className="text-[11px] mt-1" style={{ color: 'var(--muted)' }}>
          {towardsFraud ? 'Increased the fraud score' : 'Reduced the fraud score'}
        </p>
      </div>
    );
  };

  return (
    <div>
      <div style={{ height: chartHeight }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={chartData}
            layout="vertical"
            margin={{ top: 8, right: 16, left: 8, bottom: 8 }}
          >
            <XAxis
              type="number"
              domain={[-bound, bound]}
              tick={{ fill: 'var(--faint)', fontSize: 10 }}
              axisLine={{ stroke: 'var(--rule)' }}
              tickLine={{ stroke: 'var(--rule)' }}
              tickFormatter={(value: number) => value.toFixed(2)}
            />
            <YAxis
              type="category"
              dataKey="label"
              width={190}
              tick={{ fill: 'var(--faint)', fontSize: 10 }}
              axisLine={{ stroke: 'var(--rule)' }}
              tickLine={false}
            />
            <Tooltip content={customTooltip} cursor={{ fill: 'var(--accent-soft)' }} />
            <ReferenceLine x={0} stroke="var(--rule-strong)" strokeWidth={1} />
            <Bar dataKey="importance" radius={[2, 2, 2, 2]} isAnimationActive={false}>
              {chartData.map((entry) => (
                <Cell
                  key={entry.name}
                  fill={entry.importance > 0 ? riskColour : safeColour}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="flex items-center justify-center gap-6 mt-3 text-[11px]" style={{ color: 'var(--muted)' }}>
        <span className="flex items-center gap-2">
          <span className="w-3 h-3 rounded-sm" style={{ backgroundColor: riskColour }} />
          Pushed towards fraud
        </span>
        <span className="flex items-center gap-2">
          <span className="w-3 h-3 rounded-sm" style={{ backgroundColor: safeColour }} />
          Pushed towards legitimate
        </span>
      </div>
    </div>
  );
}
