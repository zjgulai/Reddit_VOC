import {
  RadarChart as ReRadarChart,
  Radar,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  ResponsiveContainer,
  Tooltip,
} from 'recharts';
import { BRAND_COLORS, NEUTRAL_COLORS } from '../../constants/colors';

interface RadarChartProps {
  data: { subject: string; value: number; fullMark?: number }[];
  title?: string;
  height?: number;
  color?: string;
  fillOpacity?: number;
}

export default function RadarChart({
  data,
  title,
  height = 280,
  color = BRAND_COLORS.primary,
  fillOpacity = 0.25,
}: RadarChartProps) {
  return (
    <div>
      {title && <div className="text-body font-medium text-foreground mb-4">{title}</div>}
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <ReRadarChart data={data}>
            <PolarGrid stroke={NEUTRAL_COLORS.gray300} />
            <PolarAngleAxis dataKey="subject" tick={{ fontSize: 12, fill: NEUTRAL_COLORS.gray500 }} />
            <PolarRadiusAxis tick={{ fontSize: 10, fill: NEUTRAL_COLORS.gray400 }} stroke={NEUTRAL_COLORS.gray300} />
            <Tooltip />
            <Radar
              dataKey="value"
              stroke={color}
              fill={color}
              fillOpacity={fillOpacity}
              strokeWidth={2}
            />
          </ReRadarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
