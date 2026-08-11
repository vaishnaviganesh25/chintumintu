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

const RISK_COLOR = '#ef4444'; // red-500  - pushed towards fraud
const SAFE_COLOR = '#10b981'; // emerald-500 - pushed towards legitimate

/**
 * Diverging bar chart of per-concept SHAP contributions.
 *
 * SHAP values are signed and additive, not shares of a whole: a value of -0.21 means
 * that concept argued *against* the fraud verdict. Rendering them on a 0-100% scale
 * would hide every mitigating factor and misrepresent the rest, so the axis is
 * symmetric around zero and direction is carried by colour.
 */
export function SHAPChart({ features }: SHAPChartProps) {
  if (features.length === 0) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400">
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
      <div className="bg-gray-800 border border-gray-600 rounded-lg p-3 shadow-lg max-w-xs">
        <p className="text-gray-200 text-sm font-medium">{name}</p>
        <p
          className={`font-semibold ${towardsFraud ? 'text-red-400' : 'text-emerald-400'}`}
        >
          {importance > 0 ? '+' : ''}
          {importance.toFixed(4)}
        </p>
        <p className="text-gray-400 text-xs mt-1">
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
              tick={{ fill: '#9ca3af', fontSize: 11 }}
              axisLine={{ stroke: '#4b5563' }}
              tickLine={{ stroke: '#4b5563' }}
              tickFormatter={(value: number) => value.toFixed(2)}
            />
            <YAxis
              type="category"
              dataKey="label"
              width={190}
              tick={{ fill: '#9ca3af', fontSize: 11 }}
              axisLine={{ stroke: '#4b5563' }}
              tickLine={false}
            />
            <Tooltip content={customTooltip} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
            <ReferenceLine x={0} stroke="#6b7280" strokeWidth={1} />
            <Bar dataKey="importance" radius={[2, 2, 2, 2]} isAnimationActive={false}>
              {chartData.map((entry) => (
                <Cell
                  key={entry.name}
                  fill={entry.importance > 0 ? RISK_COLOR : SAFE_COLOR}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="flex items-center justify-center gap-6 mt-3 text-xs text-gray-400">
        <span className="flex items-center gap-2">
          <span className="w-3 h-3 rounded-sm" style={{ backgroundColor: RISK_COLOR }} />
          Pushed towards fraud
        </span>
        <span className="flex items-center gap-2">
          <span className="w-3 h-3 rounded-sm" style={{ backgroundColor: SAFE_COLOR }} />
          Pushed towards legitimate
        </span>
      </div>
    </div>
  );
}
