import { Link } from 'react-router-dom';
import Navbar from '../components/Navbar';
import HeroSection from '../components/HeroSection';
import FeatureCard from '../components/FeatureCard';
import Accordion from '../components/Accordion';
import Footer from '../components/Footer';
import { Radar, Brain, MessageSquare } from 'lucide-react';

const features = [
  {
    icon: Radar,
    title: '版本化快照',
    description: '按发布批次展示已冻结并校验的 Reddit 公开讨论，明确数据范围与截止时间。',
  },
  {
    icon: Brain,
    title: '结构化分析',
    description: '基于当前规则模型整理主题、情感、痛点与标签，并显式展示复核边界。',
  },
  {
    icon: MessageSquare,
    title: '证据回溯',
    description: '从聚合指标回到帖子、评论与 Reddit 原文，便于核验每条洞察的依据。',
  },
];

const steps = [
  {
    number: '01',
    icon: Radar,
    title: '确认数据边界',
    description: '查看快照版本、采集范围、数据截止时间与质量说明。',
  },
  {
    number: '02',
    icon: Brain,
    title: '阅读结构化结果',
    description: '查看主题、情感、社区、品牌样本提及和已晋级标签。',
  },
  {
    number: '03',
    icon: MessageSquare,
    title: '回看原始证据',
    description: '在搜索页核对帖子与评论，并通过原始链接查看上下文。',
  },
];

const faqPreview = [
  {
    question: '当前数据如何更新？',
    answer: '当前工作台读取经过校验的版本化静态快照。新数据需先完成离线冻结、去重、关联和质量检查，再发布为新的数据版本；页面不承诺实时扫描或自动推送。',
  },
  {
    question: '结构化分析是如何工作的？',
    answer: '当前版本使用可追溯的本地规则整理主题、情感和痛点。词法标签必须通过语义抽样门禁后才能进入洞察，未晋级结果会明确标注为待复核。',
  },
  {
    question: '当前公开版本有哪些安全边界？',
    answer: '当前站点不启用登录、子账号或可写配置，只展示经处理的版本化 Reddit 公开内容快照。页面不接收 Webhook 密钥等敏感配置，也不对尚未核验的安全认证作出声明。',
  },
];

export default function Home() {
  return (
    <div className="min-h-screen bg-white">
      <Navbar />

      <HeroSection />

      {/* Features Section */}
      <section className="py-20 md:py-24">
        <div className="max-w-container mx-auto px-6 lg:px-16">
          <div className="text-center mb-12">
            <h2 className="section-title">核心功能</h2>
            <p className="section-subtitle mx-auto">
              围绕真实快照、结构化分析和原始证据组织工作台
            </p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {features.map((feature, index) => (
              <FeatureCard key={index} {...feature} />
            ))}
          </div>
        </div>
      </section>

      {/* How It Works */}
      <section className="py-20 md:py-24 bg-surface-tertiary">
        <div className="max-w-container mx-auto px-6 lg:px-16">
          <div className="text-center mb-12">
            <h2 className="section-title">三步开始分析</h2>
            <p className="section-subtitle mx-auto">
              从数据边界到原始证据，按同一条可核验链路阅读结果
            </p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 relative">
            {steps.map((step, index) => {
              const Icon = step.icon;
              return (
                <div key={index} className="relative">
                  <div className="card p-8 text-center">
                    <div className="text-[40px] font-bold text-primary/10 leading-none mb-4">
                      {step.number}
                    </div>
                    <div className="w-10 h-10 rounded-icon bg-primary-light flex items-center justify-center mx-auto mb-4">
                      <Icon className="w-5 h-5 text-primary" strokeWidth={1.5} />
                    </div>
                    <h3 className="text-h3 text-foreground mb-2">{step.title}</h3>
                    <p className="text-body-sm text-foreground-secondary">{step.description}</p>
                  </div>
                  {index < steps.length - 1 && (
                    <div className="hidden md:block absolute top-1/2 -right-3 transform -translate-y-1/2 z-10">
                      <div className="w-6 h-px bg-border" />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* FAQ Preview */}
      <section className="py-20 md:py-24">
        <div className="max-w-container mx-auto px-6 lg:px-16">
          <div className="text-center mb-12">
            <h2 className="section-title">常见问题</h2>
            <p className="section-subtitle mx-auto">
              快速了解 Reddit 舆情监测的核心问题
            </p>
          </div>
          <div className="max-w-2xl mx-auto">
            <div className="card p-8">
              <Accordion items={faqPreview} />
            </div>
            <div className="text-center mt-6">
              <Link to="/faq" className="btn-ghost text-body-sm">
                查看全部
              </Link>
            </div>
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="py-20 md:py-24">
        <div className="max-w-container mx-auto px-6 lg:px-16">
          <div className="card p-12 md:p-16 text-center bg-surface-secondary border-none">
            <h2 className="text-h1 text-foreground mb-4">准备好开始了吗？</h2>
            <p className="text-body text-foreground-secondary mb-8 max-w-md mx-auto">
              查看已校验的 Reddit VOC 静态快照
            </p>
            <Link to="/dashboard" className="btn-primary inline-flex">
              进入工作台
            </Link>
          </div>
        </div>
      </section>

      <Footer />
    </div>
  );
}
