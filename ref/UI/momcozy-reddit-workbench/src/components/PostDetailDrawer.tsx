import { useEffect, useRef } from 'react';
import {
  X,
  ArrowUpRight,
  MessageCircle,
  Clock,
  Heart,
  Share2,
  ExternalLink,
  ThumbsUp,
  ThumbsDown,
  Minus,
  Tag,
  User,
  Hash,
  BarChart3,
  Link,
} from 'lucide-react';
import FavoriteButton from './FavoriteButton';
import type { DailyNewPost } from '../data/dailyReportMock';
import { intentConfig } from '../data/intentConfig';

interface PostDetailDrawerProps {
  post: DailyNewPost | null;
  open: boolean;
  onClose: () => void;
  favoriteIds: string[];
  onToggleFavorite: (id: string) => void;
}

const sentimentConfig = {
  positive: { label: '正面', color: 'text-status-success', bg: 'bg-status-successBg', icon: ThumbsUp },
  negative: { label: '负面', color: 'text-status-error', bg: 'bg-status-errorBg', icon: ThumbsDown },
  neutral: { label: '中性', color: 'text-foreground-muted', bg: 'bg-surface-tertiary', icon: Minus },
};

export default function PostDetailDrawer({
  post,
  open,
  onClose,
  favoriteIds,
  onToggleFavorite,
}: PostDetailDrawerProps) {
  const drawerRef = useRef<HTMLDivElement>(null);
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

  if (!post) return null;

  const sentiment = sentimentConfig[post.sentiment];
  const SentimentIcon = sentiment.icon;
  const intent = intentConfig[post.intent];
  const comments = post.commentList ?? [];

  return (
    <>
      {/* Overlay */}
      <div
        ref={overlayRef}
        onClick={onClose}
        className={`fixed inset-0 bg-black/20 backdrop-blur-sm z-50 transition-opacity duration-300 ${
          open ? 'opacity-100' : 'opacity-0 pointer-events-none'
        }`}
      />

      {/* Drawer */}
      <div
        ref={drawerRef}
        className={`fixed top-0 right-0 h-full w-full sm:w-[520px] max-w-full bg-white z-50 shadow-elevated flex flex-col transition-transform duration-300 ease-smooth ${
          open ? 'translate-x-0' : 'translate-x-full'
        }`}
        role="dialog"
        aria-modal="true"
        aria-label="帖子详情"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-divider bg-white/80 backdrop-blur-xl sticky top-0 z-10">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-icon bg-primary-light flex items-center justify-center">
              <ArrowUpRight className="w-4 h-4 text-primary" strokeWidth={1.5} />
            </div>
            <div>
              <h3 className="text-body font-semibold text-foreground">帖子详情</h3>
              <p className="text-caption text-foreground-muted">r/{post.subreddit}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <FavoriteButton
              postId={post.id}
              favoriteIds={favoriteIds}
              onToggle={onToggleFavorite}
              size="md"
            />
            <button
              onClick={onClose}
              className="w-8 h-8 rounded-icon flex items-center justify-center text-foreground-muted hover:bg-surface-tertiary transition-all"
              aria-label="关闭"
            >
              <X className="w-4 h-4" strokeWidth={1.5} />
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {/* Post Title */}
          <div>
            <h2 className="text-h3 text-foreground leading-snug mb-3">{post.title}</h2>
            <div className="flex items-center gap-3 flex-wrap">
              <span className="inline-flex items-center gap-1 text-tiny text-primary bg-primary-light px-2 py-0.5 rounded-badge">
                <User className="w-3 h-3" strokeWidth={1.5} />
                u/{post.author}
              </span>
              <span className="inline-flex items-center gap-1 text-tiny text-foreground-muted">
                <Clock className="w-3 h-3" strokeWidth={1.5} />
                {post.time}
              </span>
              <span className="inline-flex items-center gap-1 text-tiny text-foreground-muted">
                <ArrowUpRight className="w-3 h-3" strokeWidth={1.5} />
                {post.upvotes} upvotes
              </span>
              <span className="inline-flex items-center gap-1 text-tiny text-foreground-muted">
                <MessageCircle className="w-3 h-3" strokeWidth={1.5} />
                {post.comments} 评论
              </span>
            </div>
          </div>

          {/* Stats Row */}
          <div className="grid grid-cols-3 gap-3">
            <div className="card p-4 text-center">
              <div className="text-[22px] font-semibold text-foreground">{post.intentScore}</div>
              <div className="text-caption text-foreground-muted mt-1">意向评分</div>
            </div>
            <div className={`card p-4 text-center ${intent.bg}`}>
              <div className={`text-[22px] font-semibold ${intent.color}`}>{intent.label}</div>
              <div className="text-caption text-foreground-muted mt-1">帖子意图</div>
            </div>
            <div className={`card p-4 text-center ${sentiment.bg}`}>
              <div className={`text-[22px] font-semibold ${sentiment.color}`}>{sentiment.label}</div>
              <div className="text-caption text-foreground-muted mt-1">情感倾向</div>
            </div>
          </div>

          {/* Reddit Metadata */}
          <div className="card p-5">
            <h4 className="text-body-sm font-semibold text-foreground mb-3">Reddit 元数据</h4>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <div className="text-center">
                <div className="flex items-center justify-center gap-1 text-tiny text-foreground-muted mb-1">
                  <Hash className="w-3 h-3" strokeWidth={1.5} />
                  Reddit ID
                </div>
                <div className="text-body-sm font-medium text-foreground truncate">{post.redditId || '-'}</div>
              </div>
              <div className="text-center">
                <div className="flex items-center justify-center gap-1 text-tiny text-foreground-muted mb-1">
                  <BarChart3 className="w-3 h-3" strokeWidth={1.5} />
                  Score
                </div>
                <div className="text-body-sm font-medium text-foreground">{post.score ?? post.upvotes}</div>
              </div>
              <div className="text-center">
                <div className="flex items-center justify-center gap-1 text-tiny text-foreground-muted mb-1">
                  <Heart className="w-3 h-3" strokeWidth={1.5} />
                  点赞比
                </div>
                <div className="text-body-sm font-medium text-foreground">
                  {post.upvoteRatio != null ? `${(post.upvoteRatio * 100).toFixed(0)}%` : '-'}
                </div>
              </div>
              <div className="text-center">
                <div className="flex items-center justify-center gap-1 text-tiny text-foreground-muted mb-1">
                  <Link className="w-3 h-3" strokeWidth={1.5} />
                  Permalink
                </div>
                <a
                  href={post.permalink || '#'}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-body-sm font-medium text-primary hover:text-primary-hover truncate block"
                  title={post.permalink || ''}
                >
                  {post.permalink ? '查看原文' : '-'}
                </a>
              </div>
            </div>
          </div>

          {/* Tags */}
          <div className="flex items-center gap-2 flex-wrap">
            <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-badge text-tiny font-medium bg-primary-light text-primary">
              <Tag className="w-3 h-3" strokeWidth={1.5} />
              r/{post.subreddit}
            </span>
            <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-badge text-tiny font-medium ${intent.bg} ${intent.color}`}>
              {intent.label}
            </span>
            <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-badge text-tiny font-medium ${sentiment.bg} ${sentiment.color}`}>
              <SentimentIcon className="w-3 h-3" strokeWidth={1.5} />
              {sentiment.label}
            </span>
          </div>

          {/* Content preview */}
          <div className="card p-5">
            <h4 className="text-body-sm font-semibold text-foreground mb-3">内容摘要</h4>
            <p className="text-body-sm text-foreground-secondary leading-relaxed">
              {post.title}
            </p>
            <div className="mt-3 pt-3 border-t border-border-divider">
              <p className="text-tiny text-foreground-muted">
                由 u/{post.author} 发布于 r/{post.subreddit}，
                情感倾向为 <span className={sentiment.color}>「{sentiment.label}」</span>，
                意向评分 {post.intentScore} 分。
                {post.intentScore >= 80
                  ? ' 这是一个高意向帖子，建议优先回复。'
                  : post.intentScore >= 50
                  ? ' 该帖子具有一定价值，建议关注。'
                  : ' 该帖子目前价值较低，可选择性监控。'}
              </p>
            </div>
          </div>

          {/* Comments */}
          <div>
            <h4 className="text-body-sm font-semibold text-foreground mb-3">
              热门评论 ({comments.length})
            </h4>
            <div className="space-y-3">
              {comments.length > 0 ? (
                comments.map((comment) => {
                  const cSentiment = sentimentConfig[comment.sentiment];
                  const CIcon = cSentiment.icon;
                  return (
                    <div key={comment.id} className="card p-4">
                      <div className="flex items-center gap-2 mb-2">
                        <span className="text-body-sm font-medium text-foreground">u/{comment.author}</span>
                        <span className="text-tiny text-foreground-muted">{comment.createdAt}</span>
                        <span className="inline-flex items-center gap-0.5 text-tiny text-foreground-muted ml-auto">
                          <ArrowUpRight className="w-3 h-3" strokeWidth={1.5} />
                          {comment.score}
                        </span>
                      </div>
                      <p className="text-body-sm text-foreground-secondary leading-relaxed">
                        {comment.body}
                      </p>
                      <div className="mt-2">
                        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-badge text-[11px] font-medium ${cSentiment.bg} ${cSentiment.color}`}>
                          <CIcon className="w-3 h-3" strokeWidth={1.5} />
                          {cSentiment.label}
                        </span>
                      </div>
                    </div>
                  );
                })
              ) : (
                <div className="card p-6 text-center text-foreground-muted text-body-sm">暂无评论数据</div>
              )}
            </div>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-3 pt-2">
            <button
              disabled
              title="即将上线"
              className="btn-primary flex-1 text-body-sm py-2.5 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Heart className="w-4 h-4 mr-1.5" strokeWidth={1.5} />
              回复帖子
            </button>
            <button
              disabled
              title="即将上线"
              className="btn-secondary flex-1 text-body-sm py-2.5 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Share2 className="w-4 h-4 mr-1.5" strokeWidth={1.5} />
              分享链接
            </button>
            <a
              href={post.permalink || '#'}
              target="_blank"
              rel="noopener noreferrer"
              className="btn-secondary w-12 h-10 flex items-center justify-center p-0"
              title="在 Reddit 中打开"
            >
              <ExternalLink className="w-4 h-4" strokeWidth={1.5} />
            </a>
          </div>
        </div>
      </div>
    </>
  );
}
