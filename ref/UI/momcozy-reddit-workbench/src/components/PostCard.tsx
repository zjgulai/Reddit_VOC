import { useState } from 'react';
import {
  Eye,
  Bookmark,
  Share2,
  Clock,
  Send,
} from 'lucide-react';

export interface PostItem {
  id: string;
  subreddit: string;
  title: string;
  intentScore: number;
  status: 'new' | 'saved' | 'viewed' | 'replied';
  author: string;
  createdAt: string;
}

interface PostCardProps {
  post: PostItem;
}

const statusConfig = {
  new: { label: '新发现', color: 'bg-[#C44A5E]/10 text-[#C44A5E]', icon: Clock },
  saved: { label: '已保存', color: 'bg-amber-50 text-amber-600', icon: Bookmark },
  viewed: { label: '已查看', color: 'bg-sky-50 text-sky-600', icon: Eye },
  replied: { label: '已回复', color: 'bg-emerald-50 text-emerald-600', icon: Send },
};

export default function PostCard({ post }: PostCardProps) {
  const [isHovered, setIsHovered] = useState(false);
  const status = statusConfig[post.status];
  const StatusIcon = status.icon;

  const getIntentColor = (score: number) => {
    if (score >= 80) return 'text-emerald-600';
    if (score >= 60) return 'text-amber-600';
    return 'text-[#A89094]';
  };

  return (
    <div
      className="card p-4 sm:p-5 transition-all duration-200"
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      <div className="flex items-start gap-4">
        {/* Intent Score */}
        <div className="flex flex-col items-center gap-1 flex-shrink-0">
          <div className="w-12 h-12 rounded-xl bg-[#F5EBE6] flex flex-col items-center justify-center">
            <span className={`text-lg font-bold ${getIntentColor(post.intentScore)}`}>
              {post.intentScore}
            </span>
            <span className="text-xs text-[#A89094]">%</span>
          </div>
          <span className="text-xs text-[#A89094]">意图</span>
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-2">
            <span className="px-2 py-0.5 rounded-md bg-[#F5EBE6] text-xs font-medium text-[#C44A5E]">
              r/{post.subreddit}
            </span>
            <span className="text-xs text-[#A89094]">u/{post.author}</span>
            <span className="text-xs text-[#A89094]">• {post.createdAt}</span>
          </div>

          <h3 className="text-sm font-semibold text-[#35141A] mb-2 truncate">
            {post.title}
          </h3>

          <div className="flex items-center gap-3">
            <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${status.color}`}>
              <StatusIcon className="w-3 h-3" />
              {status.label}
            </span>
          </div>
        </div>

        {/* Actions */}
        <div className={`flex items-center gap-2 transition-opacity duration-200 ${isHovered ? 'opacity-100' : 'opacity-0 sm:opacity-0'}`}>
          <button className="p-2 rounded-lg hover:bg-[#F5EBE6] text-[#7C5C62] transition-colors">
            <Eye className="w-4 h-4" />
          </button>
          <button className="p-2 rounded-lg hover:bg-[#F5EBE6] text-[#7C5C62] transition-colors">
            <Bookmark className="w-4 h-4" />
          </button>
          <button className="p-2 rounded-lg hover:bg-[#F5EBE6] text-[#7C5C62] transition-colors">
            <Share2 className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
