import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { X } from 'lucide-react';

export interface MetricHelpContent {
  definition: string;
  formula?: string;
  notes?: readonly string[];
}

export interface MetricHelpPopoverProps extends MetricHelpContent {
  label: string;
  align?: 'left' | 'right';
  dialogLabel?: string;
}

export default function MetricHelpPopover({
  label,
  definition,
  formula,
  notes = [],
  align = 'right',
  dialogLabel,
}: MetricHelpPopoverProps) {
  const [open, setOpen] = useState(false);
  const popoverId = useId();
  const containerRef = useRef<HTMLSpanElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  const close = useCallback((restoreFocus: boolean) => {
    setOpen(false);
    if (restoreFocus) triggerRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!open) return;

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (target instanceof Node && containerRef.current?.contains(target)) return;
      close(false);
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close(true);
    };

    document.addEventListener('pointerdown', handlePointerDown);
    window.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown);
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [close, open]);

  return (
    <span ref={containerRef} className="relative -m-3 inline-flex align-super">
      <button
        ref={triggerRef}
        type="button"
        aria-label={`${label}指标说明`}
        aria-expanded={open}
        aria-controls={popoverId}
        aria-haspopup="dialog"
        onClick={() => setOpen((value) => !value)}
        className="inline-flex h-11 w-11 items-center justify-center rounded-full text-foreground-muted transition-colors hover:text-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/35"
      >
        <span className="inline-flex h-[18px] w-[18px] items-center justify-center rounded-full border border-current bg-white text-[11px] font-semibold leading-none">?</span>
      </button>
      {open && (
        <span
          id={popoverId}
          role="dialog"
          aria-label={dialogLabel ?? `${label}计算口径`}
          className={`overlay absolute top-11 z-50 block w-[min(22rem,calc(100vw-2rem))] p-4 text-left ${
            align === 'left' ? 'left-0' : 'right-0'
          }`}
        >
          <span className="flex items-start justify-between gap-3">
            <span>
              <strong className="block text-body-sm font-semibold text-foreground">{label}</strong>
              <span className="mt-1 block text-caption font-normal leading-relaxed text-foreground-secondary">{definition}</span>
            </span>
            <button
              type="button"
              aria-label={`关闭${label}指标说明`}
              onMouseDown={(event) => {
                event.preventDefault();
                event.stopPropagation();
              }}
              onClick={(event) => {
                event.stopPropagation();
                close(true);
              }}
              className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-foreground-muted transition-colors hover:bg-surface-secondary hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
            >
              <X className="h-4 w-4" strokeWidth={1.5} aria-hidden="true" />
            </button>
          </span>
          {formula ? (
            <code className="mt-3 block whitespace-normal rounded-icon bg-primary-light/70 px-3 py-2 text-tiny font-medium leading-relaxed text-foreground">
              {formula}
            </code>
          ) : null}
          {notes.length > 0 && (
            <span className="mt-3 block space-y-1">
              {notes.map((note, index) => (
                <span key={`${note}-${index}`} className="block text-tiny font-normal leading-relaxed text-foreground-muted">· {note}</span>
              ))}
            </span>
          )}
        </span>
      )}
    </span>
  );
}
