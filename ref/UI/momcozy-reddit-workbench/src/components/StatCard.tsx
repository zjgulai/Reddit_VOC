import type { LucideIcon } from 'lucide-react';
import { TrendingUp, TrendingDown } from 'lucide-react';

interface StatCardProps {
  icon: LucideIcon;
  label: string;
  value: string;
  change: string;
  positive?: boolean;
}

export default function StatCard({ icon: Icon, label, value, change, positive = true }: StatCardProps) {
  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4">
        <div className="w-10 h-10 rounded-xl bg-[#C44A5E]/10 flex items-center justify-center">
          <Icon className="w-5 h-5 text-[#C44A5E]" />
        </div>
        <div className={`flex items-center gap-1 text-sm font-medium ${positive ? 'text-emerald-600' : 'text-[#C44A5E]'}`}>
          {positive ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
          <span>{change}</span>
        </div>
      </div>
      <div className="text-2xl font-bold text-[#35141A] mb-1">{value}</div>
      <div className="text-sm text-[#A89094]">{label}</div>
    </div>
  );
}
