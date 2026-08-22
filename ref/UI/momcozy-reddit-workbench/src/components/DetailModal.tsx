import { useEffect, useRef } from 'react';
import { X } from 'lucide-react';
import type { ReactNode } from 'react';

interface DetailModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  subtitle?: string;
  children: ReactNode;
}

export default function DetailModal({ open, onClose, title, subtitle, children }: DetailModalProps) {
  const overlayRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleEsc(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    if (open) {
      document.body.style.overflow = 'hidden';
      document.addEventListener('keydown', handleEsc);
    }
    return () => {
      document.body.style.overflow = '';
      document.removeEventListener('keydown', handleEsc);
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <>
      <div
        ref={overlayRef}
        onClick={onClose}
        className="fixed inset-0 bg-black/20 backdrop-blur-sm z-50 transition-opacity duration-300 opacity-100"
      />
      <div
        className="fixed top-0 right-0 h-full w-full sm:w-[600px] max-w-full bg-white z-50 shadow-elevated flex flex-col transition-transform duration-300 ease-smooth translate-x-0"
        role="dialog"
        aria-modal="true"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-divider bg-white/80 backdrop-blur-xl sticky top-0 z-10">
          <div>
            <h3 className="text-body font-semibold text-foreground">{title}</h3>
            {subtitle && <p className="text-caption text-foreground-muted mt-0.5">{subtitle}</p>}
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 rounded-icon flex items-center justify-center text-foreground-muted hover:bg-surface-tertiary transition-all"
            aria-label="关闭"
          >
            <X className="w-4 h-4" strokeWidth={1.5} />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          {children}
        </div>
      </div>
    </>
  );
}
