import type { LucideIcon } from 'lucide-react';

interface FeatureCardProps {
  icon: LucideIcon;
  title: string;
  description: string;
}

export default function FeatureCard({ icon: Icon, title, description }: FeatureCardProps) {
  return (
    <div className="card p-8 group">
      <div className="w-10 h-10 rounded-icon bg-primary-light flex items-center justify-center mb-5">
        <Icon className="w-5 h-5 text-primary" strokeWidth={1.5} />
      </div>
      <h3 className="text-h3 text-foreground mb-2">{title}</h3>
      <p className="text-body-sm text-foreground-secondary leading-relaxed line-clamp-2">
        {description}
      </p>
    </div>
  );
}
