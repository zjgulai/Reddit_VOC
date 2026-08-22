import { Link } from 'react-router-dom';
import Navbar from '../components/Navbar';
import Footer from '../components/Footer';
import Accordion from '../components/Accordion';
import { Mail, ArrowRight } from 'lucide-react';

const faqItems = [
  {
    question: '当前 Reddit 数据如何更新？',
    answer: '当前工作台读取经过冻结、去重、关联和质量检查的版本化静态快照。新采集数据完成后会先离线生成候选版本并完成完整性核验，通过验收后才切换发布版本；页面不承诺实时扫描或自动推送。',
  },
  {
    question: '结构化分析是如何工作的？',
    answer: '当前版本使用可追溯的本地规则整理帖子和评论的主题、情感、痛点与候选标签。候选标签还要经过语义抽样门禁；只有通过门禁的标签会进入洞察，其他结果会标注为待复核。',
  },
  {
    question: 'Dashboard 上的数量应该如何解释？',
    answer: 'Dashboard 展示当前快照内的唯一帖子、已关联评论、VOC 评论和隔离评论，并提供社区、主题、情感与品牌样本提及分布。这些都是已观察样本，不代表全量市场、市场份额、品牌健康分或连续趋势。',
  },
  {
    question: '当前支持钉钉或飞书机器人推送吗？',
    answer: '不支持。公开生产版本的该路由已改为“数据与指标口径”，展示当前发布范围、帖子/评论粒度、同环比和趋势定义；不会读取或保存 Webhook 地址和密钥，也不会进行测试发送、定时推送或 provider 调用。',
  },
  {
    question: '品牌样本提及可以当作市场份额吗？',
    answer: '不能。品牌样本提及只统计当前窗口内明确提及对应品牌的唯一帖子；同一帖子可同时提及多个品牌，因此不同品牌数量可能重复计数。没有连续、等覆盖的采集设计时，也不能把它解释为竞品趋势。',
  },
  {
    question: '帖子详情可以核验哪些信息？',
    answer: '搜索页可展示快照中的帖子标题、正文、Reddit ID、创建时间、社区、主题、情感、规则标签边界和已关联评论，并提供 Reddit 原始链接。页面不生成回复，也不把聚合画像解释为真实个人资料。',
  },
  {
    question: '如何核验日报、周报和月报？',
    answer: '报告页的当前与归档报告都绑定明确的数据版本和窗口，指标来自同一冻结快照。报告会保留覆盖缺口和外部副作用边界；使用者仍应通过搜索页和 Reddit 原始链接抽查关键证据。',
  },
  {
    question: '当前支持账号、权限和多人协作吗？',
    answer: '不支持。当前洞察站不启用登录、子账号、RBAC、回复权限或团队任务状态。页面只提供公开静态快照的只读浏览能力，不能作为协作处理系统。',
  },
  {
    question: '当前公开站点有哪些安全边界？',
    answer: '站点不接收 Webhook 密钥等敏感配置，只展示经处理的版本化 Reddit 公开内容快照。当前未启用登录与访问控制，也没有可用于声明 SOC 2、RBAC 或 AES-256 产品能力的独立证明，因此页面不作这些承诺。',
  },
  {
    question: '时间戳显示为什么不是精确的？',
    answer: '真实快照优先展示由源数据保留的 ISO 时间，并同时提供数据窗口和截止时间。首页中的帖子卡片只是功能示意，已明确标注为非实时数据，不能用于判断当前采集新鲜度。',
  },
];

export default function FAQ() {
  return (
    <div className="min-h-screen bg-white">
      <Navbar />

      <section className="pt-12 pb-16 md:pt-16 md:pb-20">
        <div className="max-w-container mx-auto px-6 lg:px-16 text-center">
          <div className="badge mb-5 inline-flex">常见问题</div>
          <h1 className="text-display text-foreground mb-4">
            有疑问？我们来解答
          </h1>
          <p className="text-body text-foreground-secondary max-w-2xl mx-auto">
            关于 Reddit 舆情监测，你可能想知道的一切
          </p>
        </div>
      </section>

      <section className="pb-16 md:pb-20">
        <div className="max-w-container mx-auto px-6 lg:px-16">
          <div className="max-w-2xl mx-auto">
            <div className="card p-8">
              <Accordion items={faqItems} />
            </div>
          </div>
        </div>
      </section>

      <section className="pb-16 md:pb-20">
        <div className="max-w-container mx-auto px-6 lg:px-16">
          <div className="max-w-2xl mx-auto">
            <div className="card p-10 md:p-12 text-center bg-surface-secondary border-none">
              <div className="w-12 h-12 rounded-full bg-primary-light flex items-center justify-center mx-auto mb-5">
                <Mail className="w-6 h-6 text-primary" strokeWidth={1.5} />
              </div>
              <h3 className="text-h2 text-foreground mb-2">需要继续核验？</h3>
              <p className="text-body text-foreground-secondary mb-6">
                先从工作台查看版本、数据边界和原始证据
              </p>
              <div>
                <Link to="/dashboard" className="btn-primary inline-flex">
                  前往工作台
                  <ArrowRight className="w-4 h-4 ml-2" strokeWidth={1.5} />
                </Link>
              </div>
            </div>
          </div>
        </div>
      </section>

      <Footer />
    </div>
  );
}
