interface HighlightTextProps {
  text: string;
  keyword: string;
  className?: string;
}

export default function HighlightText({ text, keyword, className }: HighlightTextProps) {
  if (!keyword.trim()) {
    return <span className={className}>{text}</span>;
  }

  const lowerKeyword = keyword.toLowerCase();
  const escaped = keyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const regex = new RegExp(`(${escaped})`, 'gi');
  const parts = text.split(regex);

  return (
    <span className={className}>
      {parts.map((part, i) =>
        part.toLowerCase() === lowerKeyword ? (
          <mark
            key={i}
            className="bg-primary-light text-primary font-medium rounded-sm px-0.5"
          >
            {part}
          </mark>
        ) : (
          <span key={i}>{part}</span>
        )
      )}
    </span>
  );
}
