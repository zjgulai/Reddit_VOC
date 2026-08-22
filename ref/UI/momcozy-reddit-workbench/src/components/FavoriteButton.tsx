import { Bookmark, BookmarkCheck } from 'lucide-react';

interface FavoriteButtonProps {
  postId: string;
  favoriteIds: string[];
  onToggle: (id: string) => void;
  size?: 'sm' | 'md';
}

export default function FavoriteButton({
  postId,
  favoriteIds,
  onToggle,
  size = 'sm',
}: FavoriteButtonProps) {
  const isFavorite = favoriteIds.includes(postId);

  const sizeClasses = {
    sm: 'w-8 h-8',
    md: 'w-9 h-9',
  };

  const iconSizes = {
    sm: 'w-4 h-4',
    md: 'w-5 h-5',
  };

  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        onToggle(postId);
      }}
      className={`${sizeClasses[size]} rounded-icon flex items-center justify-center transition-all duration-200 ${
        isFavorite
          ? 'bg-primary-light text-primary'
          : 'text-foreground-muted hover:bg-surface-tertiary hover:text-foreground'
      }`}
      aria-label={isFavorite ? '取消收藏' : '收藏帖子'}
      title={isFavorite ? '已收藏' : '收藏帖子'}
    >
      {isFavorite ? (
        <BookmarkCheck className={iconSizes[size]} strokeWidth={1.5} />
      ) : (
        <Bookmark className={iconSizes[size]} strokeWidth={1.5} />
      )}
    </button>
  );
}
