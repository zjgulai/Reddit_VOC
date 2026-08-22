import { useState, useMemo, useCallback } from 'react';
import { GitBranch, Tag, MessageSquare, ArrowUpRight, Clock, SearchX } from 'lucide-react';
import SectionCard from './SectionCard';
import SankeyChart from './charts/SankeyChart';
import WordCloudChart from './charts/WordCloudChart';
import PostDetailDrawer from './PostDetailDrawer';
import { useFavorites } from '../hooks/useFavorites';
import {
  topicFlowNodes,
  topicFlowLinks,
  topicFlowKeywords,
  topicFlowPosts,
  nodeToPostIds,
} from '../data/topicFlowMock';
import type { DailyNewPost } from '../data/dailyReportMock';
import type { SankeyNode, SankeyLink } from './charts/SankeyChart';
import type { WordCloudItem } from './charts/WordCloudChart';
import { intentConfig } from '../data/intentConfig';

/** 空状态 */
function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-foreground-muted">
      <SearchX className="w-10 h-10 mb-2 opacity-40" strokeWidth={1.5} />
      <p className="text-body-sm">{message}</p>
    </div>
  );
}

/** 关联帖子卡片 */
function RelatedPostCard({
  post,
  onClick,
}: {
  post: DailyNewPost;
  onClick: () => void;
}) {
  const intentColor = `${intentConfig[post.intent].color} ${intentConfig[post.intent].bg}`;

  const sentimentColor =
    post.sentiment === 'positive'
      ? 'text-status-success'
      : post.sentiment === 'negative'
      ? 'text-status-error'
      : 'text-foreground-muted';

  return (
    <button
      onClick={onClick}
      className="w-full text-left card p-4 hover:shadow-card-hover transition-all duration-300 group"
    >
      <div className="flex items-start gap-3">
        <div className="w-10 h-10 rounded-full flex items-center justify-center flex-shrink-0 border-2 bg-surface-tertiary border-border">
          <span className="text-sm font-bold text-foreground">{post.intentScore}</span>
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            <span className="text-tiny font-medium text-primary bg-primary-light px-2 py-0.5 rounded-badge">
              r/{post.subreddit}
            </span>
            <span className={`text-tiny font-medium px-2 py-0.5 rounded-badge ${intentColor}`}>
              {post.intent}
            </span>
            <span className={`text-tiny font-medium ${sentimentColor}`}>
              {post.sentiment === 'positive' ? '正面' : post.sentiment === 'negative' ? '负面' : '中性'}
            </span>
          </div>
          <h4 className="text-body-sm font-medium text-foreground leading-snug truncate group-hover:text-primary transition-colors">
            {post.title}
          </h4>
          <div className="flex items-center gap-3 mt-1.5">
            <span className="text-caption text-foreground-muted">u/{post.author}</span>
            <span className="text-caption text-foreground-muted flex items-center gap-1">
              <Clock className="w-3 h-3" strokeWidth={1.5} />
              {post.time}
            </span>
            <span className="text-caption text-foreground-muted flex items-center gap-1">
              <ArrowUpRight className="w-3 h-3" strokeWidth={1.5} />
              {post.upvotes.toLocaleString()}
            </span>
            <span className="text-caption text-foreground-muted flex items-center gap-1">
              <MessageSquare className="w-3 h-3" strokeWidth={1.5} />
              {post.comments}
            </span>
          </div>
        </div>
      </div>
    </button>
  );
}

export default function TopicFlowInsight() {
  const { favoriteIds, toggleFavorite } = useFavorites();

  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedKeyword, setSelectedKeyword] = useState<string | null>(null);
  const [drawerPost, setDrawerPost] = useState<DailyNewPost | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  // 当前选中项的名称（用于展示）
  const selectedLabel = useMemo(() => {
    if (selectedNodeId) {
      const node = topicFlowNodes.find((n) => n.id === selectedNodeId);
      return node?.name || selectedNodeId;
    }
    if (selectedKeyword) return selectedKeyword;
    return null;
  }, [selectedNodeId, selectedKeyword]);

  // 根据选中节点/关键词过滤关联帖子
  const relatedPosts = useMemo(() => {
    const key = selectedNodeId || selectedKeyword;
    if (!key) return [];
    const ids = nodeToPostIds[key] || [];
    return topicFlowPosts.filter((p) => ids.includes(p.id));
  }, [selectedNodeId, selectedKeyword]);

  // 桑基图节点点击
  const handleNodeClick = useCallback((node: SankeyNode) => {
    setSelectedKeyword(null);
    setSelectedNodeId((prev) => (prev === node.id ? null : node.id));
  }, []);

  // 桑基图连线点击
  const handleLinkClick = useCallback(
    (link: SankeyLink & { sourceName: string; targetName: string }) => {
      // 优先展示 source 节点的帖子
      setSelectedKeyword(null);
      setSelectedNodeId((prev) => (prev === link.source ? null : link.source));
    },
    []
  );

  // 词云点击
  const handleWordClick = useCallback((item: WordCloudItem) => {
    setSelectedNodeId(null);
    setSelectedKeyword((prev) => (prev === item.text ? null : item.text));
  }, []);

  // 打开帖子详情
  const openDrawer = useCallback((post: DailyNewPost) => {
    setDrawerPost(post);
    setDrawerOpen(true);
  }, []);

  const closeDrawer = useCallback(() => {
    setDrawerOpen(false);
    // 延迟清空 post 以支持动画关闭
    setTimeout(() => setDrawerPost(null), 300);
  }, []);

  return (
    <div className="space-y-6">
      <SectionCard
        title="话题流转洞察"
        subtitle="可视化追踪话题从社区传播到用户决策的完整路径"
        icon={<GitBranch className="w-5 h-5 text-primary" strokeWidth={1.5} />}
      >
        {/* 图表区域：桑基图 + 词云 */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* 桑基图 */}
          <div className="lg:col-span-7">
            <div className="card p-5 h-full">
              <div className="flex items-center gap-2 mb-4">
                <GitBranch className="w-4 h-4 text-primary" strokeWidth={1.5} />
                <span className="text-body font-medium text-foreground">话题流转路径</span>
                {selectedNodeId && (
                  <span className="ml-auto text-tiny text-primary bg-primary-light px-2 py-0.5 rounded-badge">
                    已选: {selectedLabel}
                  </span>
                )}
              </div>
              <SankeyChart
                nodes={topicFlowNodes}
                links={topicFlowLinks}
                height={380}
                nodeWidth={18}
                nodePadding={14}
                onNodeClick={handleNodeClick}
                onLinkClick={handleLinkClick}
              />
              <p className="text-caption text-foreground-muted mt-3 leading-relaxed">
                左侧为来源社区，中间为用户所处决策阶段，右侧为最终表达意图。点击节点查看关联帖子。
              </p>
            </div>
          </div>

          {/* 词云 */}
          <div className="lg:col-span-5">
            <div className="card p-5 h-full">
              <div className="flex items-center gap-2 mb-4">
                <Tag className="w-4 h-4 text-primary" strokeWidth={1.5} />
                <span className="text-body font-medium text-foreground">关联关键词</span>
                {selectedKeyword && (
                  <span className="ml-auto text-tiny text-primary bg-primary-light px-2 py-0.5 rounded-badge">
                    已选: {selectedKeyword}
                  </span>
                )}
              </div>
              <WordCloudChart
                data={topicFlowKeywords}
                height={380}
                onWordClick={handleWordClick}
              />
              <p className="text-caption text-foreground-muted mt-3 leading-relaxed">
                词云展示话题流转中的高频关键词。点击词汇筛选包含该关键词的关联帖子。
              </p>
            </div>
          </div>
        </div>

        {/* 关联帖子区域 */}
        <div className="mt-6">
          <div className="flex items-center gap-2 mb-4">
            <MessageSquare className="w-4 h-4 text-primary" strokeWidth={1.5} />
            <h4 className="text-body font-medium text-foreground">
              {selectedLabel ? `「${selectedLabel}」关联帖子` : '关联帖子'}
            </h4>
            {selectedLabel && (
              <button
                onClick={() => {
                  setSelectedNodeId(null);
                  setSelectedKeyword(null);
                }}
                className="ml-auto text-tiny text-primary hover:text-primary-hover transition-colors"
              >
                清除筛选
              </button>
            )}
          </div>

          {relatedPosts.length > 0 ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {relatedPosts.map((post) => (
                <RelatedPostCard
                  key={post.id}
                  post={post}
                  onClick={() => openDrawer(post)}
                />
              ))}
            </div>
          ) : selectedLabel ? (
            <EmptyState message={`暂无与「${selectedLabel}」直接关联的帖子`} />
          ) : (
            <div className="card p-6 text-center">
              <p className="text-body-sm text-foreground-muted">
                点击上方桑基图节点或词云关键词，查看关联帖子
              </p>
            </div>
          )}
        </div>
      </SectionCard>

      <PostDetailDrawer
        post={drawerPost}
        open={drawerOpen}
        onClose={closeDrawer}
        favoriteIds={favoriteIds}
        onToggleFavorite={toggleFavorite}
      />
    </div>
  );
}
