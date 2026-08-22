import { Link } from 'react-router-dom';
import { MessageSquare, Target, CheckCircle2 } from 'lucide-react';

export default function HeroSection() {
  return (
    <section className="relative overflow-hidden bg-white">
      <div className="max-w-container mx-auto px-6 lg:px-16 pt-16 pb-20 md:pt-20 md:pb-24">
        <div className="grid grid-cols-1 lg:grid-cols-[1.3fr_1fr] gap-10 lg:gap-14 items-center">
          {/* Left Content */}
          <div className="max-w-[720px]">
            <div className="badge mb-5 animate-fade-in">
              基于版本化真实数据快照
            </div>
            <h1 className="text-display text-foreground mb-5 animate-fade-in stagger-1">
              从 Reddit 公开讨论中发现真实用户声音
            </h1>
            <p className="text-body text-foreground-secondary mb-8 max-w-[520px] animate-fade-in stagger-2">
              汇总已冻结的帖子与评论，展示可回溯的主题、情感、痛点、报告和证据型洞察。
            </p>
            <div className="flex flex-wrap items-center gap-3 mb-10 animate-fade-in stagger-3">
              <Link to="/dashboard" className="btn-primary">
                开始使用
              </Link>
              <Link to="/how-it-works" className="btn-secondary">
                了解使用流程
              </Link>
            </div>
            {/* Stats */}
            <div className="flex items-center gap-8 animate-fade-in stagger-4">
              <div>
                <div className="text-h3 text-foreground">版本化</div>
                <div className="text-caption text-foreground-muted mt-0.5">静态快照</div>
              </div>
              <div className="w-px h-8 bg-border-divider" />
              <div>
                <div className="text-h3 text-foreground">日 · 周 · 月</div>
                <div className="text-caption text-foreground-muted mt-0.5">证据报告</div>
              </div>
              <div className="w-px h-8 bg-border-divider" />
              <div>
                <div className="text-h3 text-foreground">可回溯</div>
                <div className="text-caption text-foreground-muted mt-0.5">原始证据</div>
              </div>
            </div>
          </div>

          {/* Right: Dashboard Mockup */}
          <div className="relative flex items-center justify-center animate-fade-in stagger-3">
            <div className="relative w-full max-w-[420px]">
              <div className="card p-5 sm:p-6 relative z-10">
                {/* Header */}
                <div className="flex items-center gap-2 mb-5">
                  <div className="w-2.5 h-2.5 rounded-full bg-primary" />
                  <div className="w-2.5 h-2.5 rounded-full bg-border" />
                  <div className="w-2.5 h-2.5 rounded-full bg-border" />
                  <div className="ml-auto text-caption text-foreground-muted">功能示意 · 非实时数据</div>
                </div>

                {/* Mock post cards */}
                <div className="space-y-3">
                  {[
                    {
                      subreddit: 'r/breastfeeding',
                      time: '2分钟前',
                      title: 'Looking for a breastfeeding pump that works silently at night...',
                      score: 87,
                    },
                    {
                      subreddit: 'r/babybumps',
                      time: '5分钟前',
                      title: 'What is the best wearable breast pump for working moms?',
                      score: 92,
                    },
                    {
                      subreddit: 'r/Momcozy',
                      time: '12分钟前',
                      title: 'Need recommendations for portable breast pumps under $200',
                      score: 78,
                    },
                  ].map((post, i) => (
                    <div
                      key={i}
                      className="rounded-xl p-3.5 bg-surface-tertiary border border-border/60"
                    >
                      <div className="flex items-start gap-3">
                        <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0">
                          <MessageSquare className="w-4 h-4 text-primary" strokeWidth={1.5} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-1">
                            <span className="text-tiny text-primary font-medium">{post.subreddit}</span>
                            <span className="text-tiny text-foreground-muted">• {post.time}</span>
                          </div>
                          <p className="text-body-sm text-foreground truncate">
                            {post.title}
                          </p>
                          <div className="flex items-center gap-2 mt-1.5">
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-badge bg-primary/10 text-primary text-tiny font-medium">
                              <Target className="w-3 h-3" strokeWidth={1.5} />
                              示意标签
                            </span>
                            <span className="text-tiny text-foreground-muted">示意得分: {post.score}%</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>

                {/* Footer */}
                <div className="flex items-center gap-2 pt-3 mt-1">
                  <CheckCircle2 className="w-4 h-4 text-primary" strokeWidth={1.5} />
                  <span className="text-body-sm text-foreground-secondary">示意界面，不代表当前真实指标</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
