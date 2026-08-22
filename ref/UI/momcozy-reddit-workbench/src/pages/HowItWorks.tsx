import { Link } from 'react-router-dom';
import Navbar from '../components/Navbar';
import Footer from '../components/Footer';
import {
  Radar, Brain, MessageSquare, ArrowRight,
  LayoutDashboard, BarChart3, Lightbulb, Search,
  Inbox, Image, Bookmark, Settings, ChevronRight,
  Target, Shield, Heart, Tag, Activity, Zap
} from 'lucide-react';

const steps = [
  {
    number: '01',
    icon: Radar,
    title: '确认快照版本与范围',
    description: '先阅读数据版本、截止时间、来源和覆盖边界。',
    bullets: [
      '确认当前发布版本与完整性核验状态',
      '查看唯一帖子、关联评论和隔离数量',
      '区分已观察事实与尚未覆盖的数据',
    ],
  },
  {
    number: '02',
    icon: Brain,
    title: '阅读结构化分析',
    description: '在同一冻结窗口内查看可复现的聚合结果。',
    bullets: [
      '查看社区、主题、情感和痛点分布',
      '查看品牌样本提及而非市场份额',
      '只使用通过语义门禁的洞察标签',
    ],
  },
  {
    number: '03',
    icon: MessageSquare,
    title: '回到帖子与评论核验',
    description: '通过检索和原始链接确认指标背后的上下文。',
    bullets: [
      '按关键词或 Reddit ID 查找记录',
      '查看帖子正文与关联评论',
      '通过 Reddit 原文链接完成证据复核',
    ],
  },
];

const pagePlaybook = [
  {
    id: 'dashboard',
    title: '舆情看板',
    path: '/dashboard',
    icon: LayoutDashboard,
    color: 'bg-status-infoBg',
    iconColor: 'text-status-info',
    description: '查看当前版本化快照的总体数据质量与样本分布。',
    howTo: [
      '先确认页头的真实快照版本和数据截止时间',
      '核对唯一帖子、已关联评论、VOC 评论和隔离评论数量',
      '查看情感、主题、subreddit 与品牌样本提及分布',
      '打开代表性帖子或进入搜索页核验原始内容',
    ],
    value: [
      { side: '运营侧', desc: '用同一数据版本对齐分析口径和证据范围' },
      { side: '舆情侧', desc: '识别当前样本中的负向内容，不推断实时风险' },
      { side: '品牌侧', desc: '查看明确品牌提及样本，不解释为市场份额' },
      { side: '品类侧', desc: '了解当前采集样本中的主题和痛点构成' },
    ],
  },
  {
    id: 'analytics',
    title: '分析中心',
    path: '/dashboard/analytics',
    icon: BarChart3,
    color: 'bg-status-successBg',
    iconColor: 'text-status-success',
    description: '对冻结快照做全窗口聚合，不伪造连续时间趋势。',
    howTo: [
      '查看当前快照的正面、负面和中性样本分布',
      '比较各 subreddit、主题与痛点在样本中的数量',
      '阅读品牌样本提及，并注意多品牌帖子可能重复计数',
      '使用页面边界说明判断哪些结论当前不能支持',
    ],
    value: [
      { side: '运营侧', desc: '定位当前样本中值得进一步阅读的内容集合' },
      { side: '舆情侧', desc: '描述已观察的情感构成，不声称趋势或预警时效' },
      { side: '品牌侧', desc: '横向查看品牌明确提及样本，保留分母说明' },
      { side: '品类侧', desc: '比较主题和痛点分布，作为定性研究入口' },
    ],
  },
  {
    id: 'insights',
    title: '洞察引擎',
    path: '/dashboard/insights',
    icon: Lightbulb,
    color: 'bg-primary-light',
    iconColor: 'text-primary',
    description: '展示通过语义抽样门禁的标签和证据型聚合画像。',
    howTo: [
      '先查看已审标签数、晋级标签数与 held 标签数',
      '只把 promoted 标签解释为当前样本内的描述性信号',
      '阅读证据型聚合画像，并注意合成头像不是 Reddit 用户',
      '使用证据链接返回原始帖子或评论核验',
    ],
    value: [
      { side: '运营侧', desc: '把已复核标签作为内容阅读和研究线索' },
      { side: '舆情侧', desc: '减少词法误匹配进入洞察层的风险' },
      { side: '品牌侧', desc: '用原始证据理解样本中的明确表达' },
      { side: '品类侧', desc: '从聚合内容群识别可继续验证的问题方向' },
    ],
  },
  {
    id: 'search',
    title: '搜索发现',
    path: '/dashboard/search',
    icon: Search,
    color: 'bg-primary-light',
    iconColor: 'text-primary',
    description: '在已发布静态快照内检索真实帖子和关联评论。',
    howTo: [
      '按标题、正文、Reddit ID 或 subreddit 检索已发布记录',
      '使用情感、主题和社区筛选缩小结果范围',
      '打开帖子详情查看正文、标签边界和关联评论',
      '通过 Reddit 原文链接复核完整公开上下文',
    ],
    value: [
      { side: '运营侧', desc: '快速找到与具体问题相关的已采集内容' },
      { side: '舆情侧', desc: '从聚合指标下钻到负向文本原证据' },
      { side: '品牌侧', desc: '核对品牌提及发生在标题、正文还是评论语境' },
      { side: '品类侧', desc: '按主题和痛点组合抽取定性研究样本' },
    ],
  },
  {
    id: 'messages',
    title: '舆情信号',
    path: '/dashboard/messages',
    icon: Inbox,
    color: 'bg-surface-tertiary',
    iconColor: 'text-foreground-muted',
    description: '从真实帖子、情感、严重度和互动量生成 Momcozy VOC 优先队列。',
    howTo: [
      '查看负面或高严重度的 Momcozy 相关帖子',
      '按严重度、负面、关联评论与 Score 确定性排序',
      '进入真实搜索页核查帖子正文与评论上下文',
      '页面不伪造已读、回复、负责人或处置状态',
    ],
    value: [
      { side: '运营侧', desc: '把高影响负面信号转为可核查的阅读队列' },
      { side: '舆情侧', desc: '同时观察情感、严重度与线程放大程度' },
      { side: '品牌侧', desc: '围绕 Momcozy 主体识别风险和内容规范问题' },
      { side: '品类侧', desc: '按主题、品类与 SPU 下钻问题证据' },
    ],
  },
  {
    id: 'ugc',
    title: '高价值内容',
    path: '/dashboard/ugc-showcase',
    icon: Image,
    color: 'bg-purple-50',
    iconColor: 'text-purple-600',
    description: '从真实 Momcozy 帖子中筛选有正文、有互动和产品绑定的内容机会。',
    howTo: [
      '按关联评论、Score、情感、主题和品类查看真实候选',
      '进入搜索页核查帖子和评论证据，并导出候选清单',
      'Reddit 公开内容不等于已获得商业复用授权',
      '商业复用前仍需另行确认来源与授权',
    ],
    value: [
      { side: '运营侧', desc: '按真实互动量快速发现内容机会' },
      { side: '舆情侧', desc: '保留情感、主题和证据链路' },
      { side: '品牌侧', desc: '把内容发现与商业授权状态严格分开' },
      { side: '品类侧', desc: '按品类、产品族与 SPU 组织候选' },
    ],
  },
  {
    id: 'cases',
    title: '案例广场',
    path: '/cases',
    icon: Bookmark,
    color: 'bg-primary-light',
    iconColor: 'text-primary',
    description: '保留既有策展内容，并为审核通过的增量预留发布链路。',
    howTo: [
      '浏览「GEO」「新品机会」「舆情洞察」「商机获取」等分类案例',
      '点击案例卡片，通过来源链接核对原始内容',
      '搜索感兴趣的案例主题，如「竞品对标」「品牌危机」等',
      '既有内容继续保留，不因增量管线启用而删除',
      '新增案例只有通过来源、去重与审核后才进入发布增量',
    ],
    value: [
      { side: '运营侧', desc: '继续使用已有策展内容作为研究入口' },
      { side: '舆情侧', desc: '通过原始来源核验案例结论和适用边界' },
      { side: '品牌侧', desc: '把参考案例与本项目真实 VOC 指标分开解释' },
      { side: '品类侧', desc: '增量发布保留来源、版本和审核证据' },
    ],
  },
  {
    id: 'settings',
    title: '数据与指标口径',
    path: '/dashboard/settings',
    icon: Settings,
    color: 'bg-gray-100',
    iconColor: 'text-gray-600',
    description: '查看当前发布版本、数据范围、帖子/评论粒度及同环比计算规则。',
    howTo: [
      '核对帖子、存量评论、已关联评论与待关联评论总量',
      '理解帖子 VOC、评论 VOC 与帖子+评论上下文的计数关系',
      '查看 Momcozy、品类/SPU、同环比与趋势颜色口径',
      '页面不会读取、保存或测试 Webhook 配置',
    ],
    value: [
      { side: '运营侧', desc: '统一日报、周报、月报和洞察的业务口径' },
      { side: '舆情侧', desc: '区分采集完整性与父帖关系结构债务' },
      { side: '品牌侧', desc: '明确观察指数不是市场份额或销售结果' },
      { side: '品类侧', desc: '统一品类、产品族和 SPU 三层定义' },
    ],
  },
];

export default function HowItWorks() {
  const scrollToSection = (id: string) => {
    const el = document.getElementById(id);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  return (
    <div className="min-h-screen bg-white">
      <Navbar />

      <section className="pt-12 pb-16 md:pt-16 md:pb-20">
        <div className="max-w-container mx-auto px-6 lg:px-16 text-center">
          <div className="badge mb-5 inline-flex">使用流程</div>
          <h1 className="text-display text-foreground mb-4">
            三步开始 Reddit 舆情监测
          </h1>
          <p className="text-body text-foreground-secondary max-w-2xl mx-auto mb-7">
            按数据版本、聚合结果和原始证据三层完成核验
          </p>
          <Link to="/dashboard" className="btn-primary inline-flex">
            查看真实快照
          </Link>
        </div>
      </section>

      <section className="py-16 md:py-20">
        <div className="max-w-container mx-auto px-6 lg:px-16">
          <div className="relative">
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 lg:gap-6">
              {steps.map((step, index) => {
                const Icon = step.icon;
                return (
                  <div key={index} className="relative">
                    <div className="card p-8 h-full">
                      <div className="flex items-center gap-4 mb-5">
                        <div className="w-12 h-12 rounded-full bg-primary-light flex items-center justify-center flex-shrink-0">
                          <span className="text-[20px] font-bold text-primary">{step.number}</span>
                        </div>
                        <div className="w-10 h-10 rounded-icon bg-primary-light flex items-center justify-center">
                          <Icon className="w-5 h-5 text-primary" strokeWidth={1.5} />
                        </div>
                      </div>

                      <h3 className="text-h3 text-foreground mb-2">{step.title}</h3>
                      <p className="text-body text-foreground-secondary mb-4">{step.description}</p>

                      <ul className="space-y-2.5">
                        {step.bullets.map((bullet, i) => (
                          <li key={i} className="flex items-start gap-2.5">
                            <div className="w-1.5 h-1.5 rounded-full bg-primary mt-2 flex-shrink-0" />
                            <span className="text-body-sm text-foreground-secondary">{bullet}</span>
                          </li>
                        ))}
                      </ul>
                    </div>

                    {index < steps.length - 1 && (
                      <div className="hidden lg:flex absolute top-1/2 -right-3 transform -translate-y-1/2 z-10">
                        <div className="w-6 h-6 rounded-full bg-white border border-border flex items-center justify-center">
                          <ArrowRight className="w-3 h-3 text-foreground-muted" strokeWidth={1.5} />
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </section>

      {/* Page Playbook */}
      <section className="py-16 md:py-20 bg-surface-tertiary">
        <div className="max-w-container mx-auto px-6 lg:px-16">
          <div className="text-center mb-14">
            <div className="badge mb-4 inline-flex">Playbook</div>
            <h2 className="text-h1 text-foreground mb-4">页面使用指南</h2>
            <p className="text-body text-foreground-secondary max-w-2xl mx-auto">
              了解每个功能模块的使用方法和业务价值，让数据真正驱动决策
            </p>
          </div>

          {/* Quick Nav */}
          <div className="flex flex-wrap gap-2 mb-12 justify-center">
            {pagePlaybook.map((page) => (
              <button
                key={page.id}
                onClick={() => scrollToSection(page.id)}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-button text-body-sm font-medium transition-all border border-border-divider hover:bg-white hover:shadow-sm bg-white/50"
              >
                <page.icon className="w-3.5 h-3.5 text-foreground-muted" strokeWidth={1.5} />
                {page.title}
              </button>
            ))}
          </div>

          <div className="space-y-8">
            {pagePlaybook.map((page) => {
              const Icon = page.icon;
              return (
                <div
                  key={page.id}
                  id={page.id}
                  className="card p-6 md:p-8 scroll-mt-24 hover:shadow-card-hover transition-shadow duration-300"
                >
                  <div className="flex flex-col lg:flex-row gap-6 lg:gap-10">
                    {/* Left: Title + How To */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-3 mb-4">
                        <div className={`w-10 h-10 rounded-icon ${page.color} flex items-center justify-center`}>
                          <Icon className={`w-5 h-5 ${page.iconColor}`} strokeWidth={1.5} />
                        </div>
                        <div>
                          <h3 className="text-h3 font-semibold text-foreground">{page.title}</h3>
                          <p className="text-body-sm text-foreground-secondary">{page.description}</p>
                        </div>
                        <Link
                          to={page.path}
                          className="ml-auto inline-flex items-center gap-1 text-body-sm font-medium text-primary hover:text-primary-hover transition-colors"
                        >
                          进入页面
                          <ChevronRight className="w-4 h-4" strokeWidth={1.5} />
                        </Link>
                      </div>

                      <div className="mt-5">
                        <div className="flex items-center gap-2 mb-3">
                          <Zap className="w-4 h-4 text-primary" strokeWidth={1.5} />
                          <span className="text-body-sm font-semibold text-foreground">使用方法</span>
                        </div>
                        <ol className="space-y-2.5">
                          {page.howTo.map((item, i) => (
                            <li key={i} className="flex items-start gap-3">
                              <span className="w-5 h-5 rounded-full bg-primary-light flex items-center justify-center flex-shrink-0 mt-0.5">
                                <span className="text-[10px] font-bold text-primary">{i + 1}</span>
                              </span>
                              <span className="text-body-sm text-foreground-secondary leading-relaxed">{item}</span>
                            </li>
                          ))}
                        </ol>
                      </div>
                    </div>

                    {/* Right: Business Value */}
                    <div className="lg:w-[380px] flex-shrink-0">
                      <div className="flex items-center gap-2 mb-4">
                        <Target className="w-4 h-4 text-status-success" strokeWidth={1.5} />
                        <span className="text-body-sm font-semibold text-foreground">业务价值</span>
                      </div>
                      <div className="space-y-3">
                        {page.value.map((v, i) => {
                          const sideIcons: Record<string, typeof Activity> = {
                            '运营侧': Activity,
                            '舆情侧': Shield,
                            '品牌侧': Heart,
                            '品类侧': Tag,
                          };
                          const SideIcon = sideIcons[v.side] || Target;
                          const sideColors: Record<string, string> = {
                            '运营侧': 'text-status-info bg-status-infoBg',
                            '舆情侧': 'text-primary bg-primary-light',
                            '品牌侧': 'text-status-success bg-status-successBg',
                            '品类侧': 'text-foreground-secondary bg-surface-secondary',
                          };
                          return (
                            <div key={i} className="p-3 rounded-xl bg-surface-tertiary">
                              <div className="flex items-center gap-2 mb-1">
                                <SideIcon className={`w-3.5 h-3.5 ${sideColors[v.side].split(' ')[0]}`} strokeWidth={1.5} />
                                <span className={`text-tiny font-semibold px-1.5 py-0.5 rounded-badge ${sideColors[v.side]}`}>
                                  {v.side}
                                </span>
                              </div>
                              <p className="text-body-sm text-foreground-secondary leading-relaxed mt-1">
                                {v.desc}
                              </p>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      <section className="py-16 md:py-20">
        <div className="max-w-container mx-auto px-6 lg:px-16">
          <div className="card p-12 md:p-16 text-center bg-surface-secondary border-none">
            <h2 className="text-h1 text-foreground mb-4">开始你的证据核验</h2>
            <p className="text-body text-foreground-secondary mb-8 max-w-md mx-auto">
              从版本化数据快照进入聚合结果，并回到原始帖子和评论确认上下文
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
