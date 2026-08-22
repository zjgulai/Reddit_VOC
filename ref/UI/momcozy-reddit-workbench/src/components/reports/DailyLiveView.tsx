import { useEffect, useState } from 'react';
import { Activity, MessageSquare, TrendingUp, AlertCircle, CheckCircle, ExternalLink, FileText } from 'lucide-react';
import { PieChart } from '../charts';
import SectionCard from '../SectionCard';
import { RankedBarList } from '../../features/redditSnapshot/RankedBarList';
import { SnapshotMetricCard } from '../../features/redditSnapshot/SnapshotMetricCard';

interface DailyReportLatest {
  report_date: string;
  collected_post_count: number;
  visible_post_count: number;
  lead_sentence: string;
  sentiment_counts: Record<string, number>;
  topic_counts: Record<string, number>;
  pain_point_counts: Record<string, number>;
  voc_posts: Array<{
    社区: string;
    帖子链接: string;
    标题原文: string;
    标题中文: string;
    情感: string;
    内容类型: string;
    主题: string;
    摘要中文: string;
  }>;
  status: "ok" | "no_report_today" | "error";
  run_id: string;
  window_start_utc: string;
  window_end_utc: string;
}

export default function DailyLiveView() {
  const [data, setData] = useState<DailyReportLatest | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    fetch('/api/daily-report/latest')
      .then(res => {
        if (!res.ok) throw new Error(`HTTP error ${res.status}`);
        return res.json();
      })
      .then(json => {
        if (active) {
          setData(json);
          setIsLoading(false);
        }
      })
      .catch(err => {
        if (active) {
          setError(err instanceof Error ? err.message : 'Unknown error');
          setIsLoading(false);
        }
      });
    return () => { active = false; };
  }, []);

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-foreground-muted">
        <Activity className="h-8 w-8 animate-pulse mb-4 opacity-50" />
        <p>正在加载今日采集动态...</p>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="rounded-xl border border-status-error/30 bg-status-errorBg p-6 text-status-error">
        <div className="flex items-center gap-2 mb-2">
          <AlertCircle className="h-5 w-5" />
          <h3 className="font-medium">加载失败</h3>
        </div>
        <p className="text-sm opacity-80">{error || '无法获取今日动态'}</p>
      </div>
    );
  }

  if (data.status === 'no_report_today') {
    return (
      <div className="rounded-xl border border-amber-200 bg-amber-50 p-8 text-center text-amber-900">
        <AlertCircle className="h-8 w-8 mx-auto mb-4 opacity-50" />
        <h3 className="font-medium text-lg mb-2">今日暂无报告</h3>
        <p className="text-sm opacity-80">采集任务可能尚未运行或未能获取到新数据。</p>
      </div>
    );
  }
  
  const SENTIMENT_COLORS: Record<string, string> = {
    '正面': '#18A874',
    '中性': '#98A2B3',
    '负面': '#E85D75'
  };

  const sentimentData = Object.entries(data.sentiment_counts).map(([name, value]) => ({
    name,
    value,
    color: SENTIMENT_COLORS[name] || '#98A2B3'
  }));

  const topicData = Object.entries(data.topic_counts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([name, value]) => ({ label: name, value }));

  const painPointData = Object.entries(data.pain_point_counts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([name, value]) => ({ label: name, value }));

  return (
    <div className="flex flex-col gap-6">
      {/* 顶部状态行 */}
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-border-divider/60 bg-white px-5 py-4 shadow-sm">
        <div className="flex items-center gap-3">
          {data.status === 'ok' ? (
            <CheckCircle className="h-5 w-5 text-status-success" />
          ) : data.status === 'error' ? (
            <AlertCircle className="h-5 w-5 text-status-error" />
          ) : (
            <Activity className="h-5 w-5 text-amber-500" />
          )}
          <div>
            <p className="font-medium text-foreground">当日采集动态 · {data.report_date}</p>
            <p className="text-caption text-foreground-muted">
              采集窗口: {new Date(data.window_start_utc).toLocaleString()} - {new Date(data.window_end_utc).toLocaleString()}
            </p>
          </div>
        </div>
        <div className="text-right">
          <p className="text-caption text-foreground-muted">Run ID</p>
          <p className="font-mono text-tiny text-foreground-secondary">{data.run_id}</p>
        </div>
      </div>

      {/* 指标卡片 */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <SnapshotMetricCard
          label="采集帖子数"
          value={data.collected_post_count}
          icon={Activity}
          note="原始采集总数"
        />
        <SnapshotMetricCard
          label="过滤后可见数"
          value={data.visible_post_count}
          icon={CheckCircle}
          note="处理后纳入统计数量"
          tone="success"
        />
        <div className="col-span-1 sm:col-span-3 rounded-xl border border-border-divider/60 bg-white p-5 shadow-sm">
          <h3 className="text-sm font-medium text-foreground-muted mb-2">今日导语</h3>
          <p className="text-foreground leading-relaxed">{data.lead_sentence}</p>
        </div>
      </div>

      {/* 分布图表 */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <SectionCard 
          title="情感分布"
          icon={<MessageSquare className="h-5 w-5" />}
        >
          <div className="flex h-[240px] items-center justify-center">
            <PieChart data={sentimentData} />
          </div>
        </SectionCard>

        <SectionCard 
          title="热门主题 Top 5"
          icon={<TrendingUp className="h-5 w-5" />}
        >
          <RankedBarList items={topicData} />
        </SectionCard>
      </div>

      {/* 痛点分布 */}
      <SectionCard 
        title="核心痛点 Top 5"
        icon={<AlertCircle className="h-5 w-5 text-status-error" />}
      >
        <RankedBarList items={painPointData} colorClass="bg-status-warning" />
      </SectionCard>

      {/* 帖子列表 */}
      <SectionCard 
        title={`今日 VOC 帖子 (${data.voc_posts.length} 条记录)`}
        icon={<FileText className="h-5 w-5" />}
      >
        <div className="flex flex-col gap-3 max-h-[600px] overflow-y-auto pr-2">
          {data.voc_posts.map((post, i) => (
            <div key={i} className="rounded-lg border border-border-divider/50 bg-surface-secondary/30 p-4 transition-colors hover:bg-surface-secondary">
              <div className="flex flex-wrap items-start justify-between gap-2 mb-2">
                <div className="flex items-center gap-2">
                  <span className="rounded bg-surface-tertiary px-2 py-0.5 text-xs font-medium text-foreground-secondary">
                    {post.社区}
                  </span>
                  <span className={`rounded px-2 py-0.5 text-xs font-medium ${
                    post.情感 === '正面' ? 'bg-status-successBg text-status-success' : 
                    post.情感 === '负面' ? 'bg-status-errorBg text-status-error' : 
                    'bg-surface-tertiary text-foreground-secondary'
                  }`}>
                    {post.情感}
                  </span>
                  <span className="rounded border border-border-divider px-2 py-0.5 text-xs text-foreground-muted">
                    {post.内容类型}
                  </span>
                </div>
                <a 
                  href={post.帖子链接} 
                  target="_blank" 
                  rel="noopener noreferrer"
                  className="flex items-center gap-1 text-xs text-primary hover:underline"
                >
                  查看原帖 <ExternalLink className="h-3 w-3" />
                </a>
              </div>
              <h4 className="font-medium text-foreground mb-1">{post.标题中文}</h4>
              <p className="text-xs text-foreground-muted mb-2 line-clamp-1">{post.标题原文}</p>
              <div className="rounded bg-white/50 p-3 text-sm text-foreground-secondary">
                <p className="mb-2"><span className="font-medium text-foreground">主题：</span>{post.主题}</p>
                <p><span className="font-medium text-foreground">摘要：</span>{post.摘要中文}</p>
              </div>
            </div>
          ))}
        </div>
      </SectionCard>
    </div>
  );
}
