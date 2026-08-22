import type { LucideIcon } from 'lucide-react';

interface InsightCardProps {
  icon: LucideIcon;
  title: string;
  description: string;
  highlight: string;
}

export default function InsightCard({ icon: Icon, title, description, highlight }: InsightCardProps) {
  return (
    <div className="card p-4">
      <div className="flex items-start gap-3">
        <div className="w-9 h-9 rounded-lg bg-[#C44A5E]/10 flex items-center justify-center shrink-0">
          <Icon className="w-5 h-5 text-[#C44A5E]" />
        </div>
        <div className="flex-1">
          <h4 className="text-sm font-semibold text-[#35141A] mb-1">{title}</h4>
          <p className="text-xs text-[#7C5C62] leading-relaxed mb-2">{description}</p>
          <div className="inline-flex items-center px-2.5 py-1 rounded-full bg-[#C44A5E]/10 text-xs font-medium text-[#C44A5E]">
            {highlight}
          </div>
        </div>
      </div>
    </div>
  );
}
