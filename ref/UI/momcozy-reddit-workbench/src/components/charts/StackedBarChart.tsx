import {
  BarChart as ReBarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts';

interface StackedBarChartProps {
  data: { name: string; [key: string]: string | number }[];
  keys: { key: string; color: string; name: string }[];
  title?: string;
  height?: number;
}

export default function StackedBarChart({ data, keys, title, height = 280 }: StackedBarChartProps) {
  return (
    <div>
      {title && <div className="text-body font-medium text-foreground mb-4">{title}</div>}
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <ReBarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
            <XAxis dataKey="name" tick={{ fontSize: 12 }} />
            <YAxis tick={{ fontSize: 12 }} />
            <Tooltip />
            <Legend />
            {keys.map((k) => (
              <Bar
                key={k.key}
                dataKey={k.key}
                name={k.name}
                stackId="a"
                fill={k.color}
                radius={[0, 0, 0, 0]}
              />
            ))}
          </ReBarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
