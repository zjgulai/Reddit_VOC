import {
  ScatterChart as ReScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ZAxis,
  Cell,
} from 'recharts';
import { CHART_PALETTE, BRAND_COLORS, NEUTRAL_COLORS } from '../../constants/colors';

interface ScatterChartProps {
  data: { x: number; y: number; z?: number; name?: string; color?: string }[];
  title?: string;
  height?: number;
  xAxisName?: string;
  yAxisName?: string;
  defaultColor?: string;
}

const DEFAULT_COLORS = CHART_PALETTE.slice(0, 6);

export default function ScatterChart({
  data,
  title,
  height = 280,
  xAxisName = 'X轴',
  yAxisName = 'Y轴',
  defaultColor = BRAND_COLORS.primary,
}: ScatterChartProps) {
  return (
    <div>
      {title && <div className="text-body font-medium text-foreground mb-4">{title}</div>}
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <ReScatterChart>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
            <XAxis
              type="number"
              dataKey="x"
              name={xAxisName}
              tick={{ fontSize: 12 }}
              label={{ value: xAxisName, position: 'insideBottom', offset: -2, fontSize: 12, fill: NEUTRAL_COLORS.gray400 }}
            />
            <YAxis
              type="number"
              dataKey="y"
              name={yAxisName}
              tick={{ fontSize: 12 }}
              label={{ value: yAxisName, angle: -90, position: 'insideLeft', fontSize: 12, fill: NEUTRAL_COLORS.gray400 }}
            />
            <ZAxis type="number" dataKey="z" range={[60, 400]} />
            <Tooltip cursor={{ strokeDasharray: '3 3' }} />
            <Scatter data={data} fill={defaultColor}>
              {data.map((entry, index) => (
                <Cell
                  key={`cell-${index}`}
                  fill={entry.color || DEFAULT_COLORS[index % DEFAULT_COLORS.length]}
                />
              ))}
            </Scatter>
          </ReScatterChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
