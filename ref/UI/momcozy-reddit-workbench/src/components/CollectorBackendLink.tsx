import { ExternalLink } from 'lucide-react';
import { Link } from 'react-router-dom';

export const COLLECTOR_BACKEND_URL = '/dashboard/reports?period=daily';

interface CollectorBackendLinkProps {
  placement: 'header' | 'sidebar';
  collapsed?: boolean;
}

export default function CollectorBackendLink({
  placement,
  collapsed = false,
}: CollectorBackendLinkProps) {
  const isSidebar = placement === 'sidebar';

  return (
    <Link
      to={COLLECTOR_BACKEND_URL}
      aria-label="最新日报"
      title={collapsed ? '最新日报' : undefined}
      className={
        isSidebar
          ? `flex items-center ${
              collapsed ? 'justify-center px-2' : 'gap-3 px-3'
            } w-full rounded-icon py-2.5 text-body-sm font-medium text-foreground-secondary transition-all duration-300 hover:bg-surface-tertiary hover:text-foreground`
          : 'inline-flex shrink-0 items-center gap-2 rounded-badge border border-border-divider bg-white px-3 py-1.5 text-tiny font-medium text-foreground-secondary transition-colors hover:border-primary/30 hover:bg-primary-light hover:text-primary'
      }
    >
      <ExternalLink
        className={isSidebar ? 'h-[18px] w-[18px] shrink-0' : 'h-3.5 w-3.5 shrink-0'}
        strokeWidth={1.5}
      />
      {(!isSidebar || !collapsed) && <span>最新日报</span>}
    </Link>
  );
}
