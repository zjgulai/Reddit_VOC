import { Link } from 'react-router-dom';
import {
  Radar,
  Brain,
  Bot,
  Check,
  ArrowRight,
  MessageSquare,
  BarChart3,
  Zap,
  Sparkles,
  Shield,
  Globe,
} from 'lucide-react';
import Navbar from '../components/Navbar';
import Footer from '../components/Footer';

const features = [
  {
    icon: Radar,
    title: '版本化数据快照',
    description: '展示经过冻结、去重与完整性校验的 Reddit 公开内容批次，不把采集中的数据冒充为已发布结果。',
    bullets: ['记录数据版本与截止时间', '帖子和评论保持可追溯关联', '快照校验失败时停止展示指标'],
    illustration: (
      <div className="w-full h-full flex items-center justify-center">
        <div className="relative w-48 h-48">
          <div className="absolute inset-0 rounded-full bg-surface-secondary" />
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-16 h-16 rounded-full bg-primary-light flex items-center justify-center">
            <Radar className="w-8 h-8 text-primary" strokeWidth={1.5} />
          </div>
          <div className="absolute top-4 right-4 w-3 h-3 rounded-full bg-status-success/30" />
          <div className="absolute bottom-8 left-8 w-2 h-2 rounded-full bg-primary/20" />
          <div className="absolute top-8 left-12 w-2 h-2 rounded-full bg-foreground-muted/20" />
        </div>
      </div>
    ),
  },
  {
    icon: Brain,
    title: '结构化 VOC 分析',
    description: '使用可追溯的本地规则整理主题、情感、痛点和词法标签，并对标签结果设置独立语义复核门禁。',
    bullets: ['主题与情感分布', '痛点和品牌样本提及', '仅展示通过门禁的洞察标签'],
    illustration: (
      <div className="w-full h-full flex items-center justify-center">
        <div className="relative w-48 h-48">
          <div className="absolute inset-0 rounded-full bg-surface-secondary" />
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-16 h-16 rounded-full bg-primary-light flex items-center justify-center">
            <Brain className="w-8 h-8 text-primary" strokeWidth={1.5} />
          </div>
          <div className="absolute top-6 right-8 bg-white rounded-badge px-3 py-1 shadow-card">
            <span className="text-tiny font-medium text-status-success">已观察证据</span>
          </div>
          <div className="absolute bottom-6 left-6 bg-white rounded-badge px-3 py-1 shadow-card">
            <span className="text-tiny font-medium text-foreground-muted">待语义复核</span>
          </div>
        </div>
      </div>
    ),
  },
  {
    icon: Bot,
    title: '证据检索与回溯',
    description: '从聚合结果下钻到真实帖子、关联评论和 Reddit 原始链接，帮助使用者自行核验结论。',
    bullets: ['按关键词和 Reddit ID 检索', '查看帖子与高分关联评论', '回到 Reddit 原文确认上下文'],
    illustration: (
      <div className="w-full h-full flex items-center justify-center">
        <div className="relative w-48 h-48">
          <div className="absolute inset-0 rounded-full bg-surface-secondary" />
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-16 h-16 rounded-full bg-primary-light flex items-center justify-center">
            <Bot className="w-8 h-8 text-primary" strokeWidth={1.5} />
          </div>
          <div className="absolute top-4 left-4 bg-white rounded-card p-2 shadow-card">
            <div className="w-12 h-1.5 bg-border rounded-full mb-1" />
            <div className="w-8 h-1.5 bg-border rounded-full" />
          </div>
          <div className="absolute bottom-4 right-4 bg-primary rounded-card p-2 shadow-card">
            <div className="w-12 h-1.5 bg-white/40 rounded-full mb-1" />
            <div className="w-8 h-1.5 bg-white/40 rounded-full" />
          </div>
        </div>
      </div>
    ),
  },
];

export default function Features() {
  return (
    <div className="min-h-screen bg-white">
      <Navbar />

      {/* Hero */}
      <section className="pt-12 pb-16 lg:pt-16 lg:pb-20">
        <div className="max-w-container mx-auto px-4 sm:px-6 lg:px-16 text-center">
          <div className="badge mb-5 inline-flex">
            <Sparkles className="w-3.5 h-3.5 mr-1.5" strokeWidth={1.5} />
            功能一览
          </div>
          <h1 className="text-display text-foreground mb-4 tracking-tight">
            强大的 Reddit 舆情管理工具
          </h1>
          <p className="text-body text-foreground-secondary max-w-[560px] mx-auto mb-7">
            从监测到分析，从洞察到行动，一站式 Reddit 舆情管理解决方案
          </p>
          <div className="flex flex-wrap items-center justify-center gap-4">
            <Link to="/dashboard" className="btn-primary">
              开始使用
              <ArrowRight className="w-4 h-4 ml-2" strokeWidth={1.5} />
            </Link>
            <Link to="/how-it-works" className="btn-ghost">
              了解使用流程
            </Link>
          </div>
        </div>
      </section>

      {/* Feature Sections */}
      <div className="space-y-0">
        {features.map((feature, index) => {
          const Icon = feature.icon;
          const isReversed = index % 2 === 1;
          return (
            <section
              key={feature.title}
              className={`py-16 lg:py-20 ${index === 1 ? 'bg-surface-tertiary' : 'bg-white'}`}
            >
              <div className="max-w-container mx-auto px-4 sm:px-6 lg:px-16">
                <div className={`grid grid-cols-1 lg:grid-cols-2 gap-10 lg:gap-16 items-center ${
                  isReversed ? 'lg:flex-row-reverse' : ''
                }`}
                >
                  <div className={isReversed ? 'lg:order-2' : 'lg:order-1'}>
                    <div className="w-12 h-12 rounded-icon bg-primary-light flex items-center justify-center mb-5">
                      <Icon className="w-6 h-6 text-primary" strokeWidth={1.5} />
                    </div>
                    <h2 className="text-h1 text-foreground mb-4">{feature.title}</h2>
                    <p className="text-body text-foreground-secondary leading-relaxed mb-5">
                      {feature.description}
                    </p>
                    <ul className="space-y-3">
                      {feature.bullets.map((bullet) => (
                        <li key={bullet} className="flex items-start gap-3">
                          <div className="w-5 h-5 rounded-full bg-status-successBg flex items-center justify-center flex-shrink-0 mt-0.5">
                            <Check className="w-3 h-3 text-status-success" strokeWidth={1.5} />
                          </div>
                          <span className="text-body-sm text-foreground-secondary">{bullet}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div className={`${isReversed ? 'lg:order-1' : 'lg:order-2'}`}>
                    <div className="card h-[320px] flex items-center justify-center border border-border/60">
                      {feature.illustration}
                    </div>
                  </div>
                </div>
              </div>
            </section>
          );
        })}
      </div>

      {/* Additional Features Grid */}
      <section className="py-16 lg:py-20 bg-surface-tertiary">
        <div className="max-w-container mx-auto px-4 sm:px-6 lg:px-16">
          <div className="text-center mb-12">
            <h2 className="section-title">更多能力</h2>
            <p className="section-subtitle mx-auto">
              全面的工具集，满足你的所有 Reddit 舆情管理需求
            </p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
            {[
              { icon: Globe, title: '多社区样本', desc: '按快照记录已采集 subreddit 的实际内容分布' },
              { icon: Shield, title: '边界显式', desc: '明确区分已观察事实、推断、覆盖缺口与待复核结果' },
              { icon: BarChart3, title: '证据报告', desc: '基于同一快照生成日报、周报和月报视图' },
              { icon: MessageSquare, title: '帖子检索', desc: '检索真实帖子与评论，不回退到演示数据' },
              { icon: Zap, title: '聚合洞察', desc: '展示社区、主题、情感、痛点和品牌样本提及' },
              { icon: Sparkles, title: '失败关闭', desc: 'manifest 或文件校验失败时停止渲染相关指标' },
            ].map((item) => {
              const ItemIcon = item.icon;
              return (
                <div key={item.title} className="card p-6">
                  <div className="w-10 h-10 rounded-icon bg-primary-light flex items-center justify-center mb-4">
                    <ItemIcon className="w-5 h-5 text-primary" strokeWidth={1.5} />
                  </div>
                  <h3 className="text-h4 text-foreground mb-2">{item.title}</h3>
                  <p className="text-body-sm text-foreground-secondary">{item.desc}</p>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="py-16 lg:py-20">
        <div className="max-w-container mx-auto px-4 sm:px-6 lg:px-16">
          <div className="card p-12 lg:p-16 text-center bg-surface-secondary border-none">
            <h2 className="text-h1 text-foreground mb-4">
              准备好开始了吗？
            </h2>
            <p className="text-body text-foreground-secondary max-w-lg mx-auto mb-8">
              从真实快照开始核验 Reddit VOC 数据
            </p>
            <Link to="/dashboard" className="btn-primary inline-flex">
              开始使用
              <ArrowRight className="w-4 h-4 ml-2" strokeWidth={1.5} />
            </Link>
          </div>
        </div>
      </section>

      <Footer />
    </div>
  );
}
