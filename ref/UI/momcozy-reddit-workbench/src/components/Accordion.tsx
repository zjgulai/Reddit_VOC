import { useState, useRef, useLayoutEffect, useEffect, useId, useCallback } from 'react';
import { ChevronDown } from 'lucide-react';

interface AccordionItem {
  question: string;
  answer: string;
}

interface AccordionProps {
  items: AccordionItem[];
  allowMultiple?: boolean;
}

export default function Accordion({ items, allowMultiple = false }: AccordionProps) {
  const [openIndexes, setOpenIndexes] = useState<Set<number>>(new Set());
  const [heights, setHeights] = useState<Record<number, number>>({});
  const contentRefs = useRef<Record<number, HTMLDivElement | null>>({});
  const baseId = useId();

  const measureHeights = useCallback(() => {
    const newHeights: Record<number, number> = {};
    items.forEach((_, i) => {
      const el = contentRefs.current[i];
      if (el) newHeights[i] = el.scrollHeight;
    });
    setHeights(newHeights);
  }, [items]);

  // Measure on mount / items change (layout effect to ensure DOM is ready)
  useLayoutEffect(() => {
    measureHeights();
  }, [measureHeights]);

  // Re-measure on window resize
  useEffect(() => {
    const handleResize = () => measureHeights();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [measureHeights]);

  const toggle = (index: number) => {
    setOpenIndexes(prev => {
      const next = new Set(prev);
      if (next.has(index)) {
        next.delete(index);
      } else {
        if (!allowMultiple) {
          next.clear();
        }
        next.add(index);
      }
      return next;
    });
  };

  return (
    <div className="w-full" role="region" aria-label="常见问题">
      {items.map((item, index) => {
        const isOpen = openIndexes.has(index);
        const panelId = `${baseId}-panel-${index}`;
        const triggerId = `${baseId}-trigger-${index}`;
        return (
          <div key={index} className="w-full">
            <button
              id={triggerId}
              onClick={() => toggle(index)}
              className="w-full flex items-center justify-between py-5 text-left group"
              aria-expanded={isOpen}
              aria-controls={panelId}
            >
              <span className="text-base font-medium text-foreground pr-4 leading-relaxed">
                {item.question}
              </span>
              <ChevronDown
                className={`w-5 h-5 text-foreground-muted flex-shrink-0 transition-transform duration-300 ease-smooth ${
                  isOpen ? 'rotate-180' : ''
                }`}
                strokeWidth={1.5}
                aria-hidden="true"
              />
            </button>
            <div
              id={panelId}
              role="region"
              aria-labelledby={triggerId}
              className="overflow-hidden transition-all duration-300 ease-smooth"
              style={{
                maxHeight: isOpen ? `${heights[index] || 0}px` : '0px',
                opacity: isOpen ? 1 : 0,
              }}
            >
              <div
                ref={(el) => { contentRefs.current[index] = el; }}
                className="pb-5"
              >
                <p className="text-body text-foreground-secondary leading-relaxed">
                  {item.answer}
                </p>
              </div>
            </div>
            {index < items.length - 1 && <div className="divider" />}
          </div>
        );
      })}
    </div>
  );
}
