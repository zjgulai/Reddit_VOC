import {
  AlertTriangle,
  ArrowRight,
  CalendarRange,
  CheckCircle2,
  CircleHelp,
  Compass,
  GalleryVerticalEnd,
  Lightbulb,
  MessageSquareText,
  PackageSearch,
  Search,
  ShieldCheck,
  Sparkles,
  Target,
  UsersRound,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import type { KeyboardEvent, ReactNode } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import type { RedditPublicCasebook } from '../../features/redditSnapshot/casebook';
import {
  CROSS_PAGE_RECONCILIATION_RULE_CN,
  crossPageReconciliationAttributes,
} from '../../features/redditSnapshot/crossPageReconciliation';
import { buildSnapshotEvidenceHref } from '../../features/redditSnapshot/evidenceLinks';

// 证据卡的标题来自季度投影的审核理由码。生产者若只给内部码（如
// product_evaluation_signal，2026-11-05 审计发现五张卡同名），按此映射转成
// 中文；未收录的码原样显示，新码出现时不会丢信息。
const EVIDENCE_REASON_LABELS: Record<string, string> = {
  product_evaluation_signal: '产品评价信号',
  competitor_comparison_signal: '竞品比较信号',
  pain_point_observed: '痛点观察',
  negative_or_high_severity_signal: '负面或高严重度信号',
  purchase_decision_signal: '购买决策信号',
};
import type {
  QuarterInsightEvidence,
  QuarterInsightRanking,
  RedditQuarterInsightsData,
} from '../../features/redditSnapshot/quarterInsights';
import type { RedditSnapshotCore } from '../../features/redditSnapshot/types';
import type { PersonasState } from '../../features/redditSnapshot/useRedditPersonas';
import type { V3RedditInsightsSnapshot } from '../../features/redditSnapshot/insightsV3';
import { createBaseDataFreshness } from '../../features/redditSnapshot/freshness';
import { SnapshotPageLayout } from '../../features/redditSnapshot/SnapshotPageLayout';
import AggregatePersonaPanel from '../personas/AggregatePersonaPanel';

type ThemeId = 'pain' | 'reputation' | 'new-product' | 'geo';
type ArtifactThemeId = 'pain' | 'reputation' | 'new_product' | 'geo';
type Priority = 'P0' | 'P1' | 'P2';

interface ThemeSignal {
  label: string;
  note: string;
  value: string;
}

interface ThemeAction {
  detail: string;
  priority: Priority;
  title: string;
}

interface RankingGroup {
  items: QuarterInsightRanking[];
  note: string;
  title: string;
}

interface ThemeViewModel {
  actions: ThemeAction[];
  artifactThemeId: ArtifactThemeId;
  boundary: string;
  businessExplanation: string[];
  evidence: QuarterInsightEvidence[];
  icon: LucideIcon;
  id: ThemeId;
  label: string;
  managementQuestion: string;
  rankings: RankingGroup[];
  signals: ThemeSignal[];
  summary: string;
}

const themeOrder: ThemeId[] = ['pain', 'reputation', 'new-product', 'geo'];

const themeMeta: Record<ThemeId, { icon: LucideIcon; label: string; shortLabel: string }> = {
  pain: { icon: Target, label: '用户痛点', shortLabel: '体验阻力' },
  reputation: { icon: ShieldCheck, label: '舆情与内容合规', shortLabel: '声誉风险' },
  'new-product': { icon: PackageSearch, label: '新品机会', shortLabel: '未满足需求' },
  geo: { icon: Compass, label: 'GEO 优化机会', shortLabel: '决策内容' },
};

function formatNumber(value: number): string {
  return value.toLocaleString('zh-CN');
}

function rankingValue(items: QuarterInsightRanking[], id: string): number {
  return items.find((item) => item.id === id)?.count ?? 0;
}

function buildThemeViewModel(
  theme: ThemeId,
  quarterInsights: RedditQuarterInsightsData,
): ThemeViewModel {
  const { counts, themes } = quarterInsights;
  const common = {
    icon: themeMeta[theme].icon,
    id: theme,
    label: themeMeta[theme].label,
  } as const;

  if (theme === 'pain') {
    const topPain = themes.pain.rankings[0];
    return {
      ...common,
      artifactThemeId: 'pain',
      managementQuestion: '最近一个季度，Momcozy 最需要优先解决哪些真实体验阻力？',
      summary: `${topPain.label}以 ${formatNumber(topPain.count)} 条多标签 VOC 位居首位，优先级高于适配舒适度与泌乳输出问题。`,
      signals: [
        { label: 'Momcozy VOC', value: formatNumber(counts.momcozy.total_vocs), note: `${formatNumber(counts.momcozy.post_vocs)} 帖子 VOC + ${formatNumber(counts.momcozy.comment_context_vocs)} 评论上下文 VOC` },
        { label: '首要痛点', value: formatNumber(topPain.count), note: topPain.label },
        { label: '负向 VOC', value: formatNumber(counts.momcozy.sentiment.negative), note: `占 ${formatNumber(counts.momcozy.sentiment.classified)} 条已分类 VOC 的 ${counts.momcozy.sentiment.negative_rate.toFixed(2)}%` },
      ],
      rankings: [{
        title: '痛点主题分布',
        note: '同一 VOC 可以命中多个主题，条数不可相加为独立用户人数。',
        items: themes.pain.rankings,
      }],
      evidence: themes.pain.evidence,
      businessExplanation: [
        '操作与可靠性是当前最大的体验摩擦，应先按安全、故障、耐用性、替换时效拆成可归责问题清单。',
        '适配舒适度与泌乳输出紧随其后，说明产品、使用教育和个体适配需要在同一闭环内判断，不能把全部问题归为操作不当。',
        '该排序用于配置复核资源，不代表用户人口占比、市场份额或问题发生率。',
      ],
      actions: [
        { priority: 'P0', title: '逐条复核高风险证据', detail: '由产品质量、客服和社区运营共同核查安全、故障、泄漏与更换延迟证据，形成责任人和响应时限。' },
        { priority: 'P1', title: '按品类与产品家族拆解', detail: '把操作可靠性、适配舒适度和输出供给问题交叉到品类及产品家族，避免用总量掩盖局部问题。' },
        { priority: 'P2', title: '沉淀预防型内容', detail: '把已确认根因与解决路径转成安装、清洁、适配、故障排查和售后 FAQ，并持续观察复发。' },
      ],
      boundary: '痛点来自现有标签字典与受治理事实的多标签观察；同一内容可重复进入多个主题。',
    };
  }

  if (theme === 'reputation') {
    return {
      ...common,
      artifactThemeId: 'reputation',
      managementQuestion: '哪些信号可能伤害社区信任，Momcozy 应如何在不越界归因的前提下治理？',
      summary: `季度内观察到 ${formatNumber(themes.reputation.negative_vocs)} 条负向 VOC、${formatNumber(themes.reputation.high_severity_vocs)} 条高严重度 VOC，以及 ${formatNumber(themes.reputation.automation_comments)} 条自动化评论。`,
      signals: [
        { label: '负向 VOC', value: formatNumber(themes.reputation.negative_vocs), note: `已分类分母负向占比 ${counts.momcozy.sentiment.negative_rate.toFixed(2)}%` },
        { label: '高严重度 VOC', value: formatNumber(themes.reputation.high_severity_vocs), note: '用于安排人工复核优先级，不等于已确认危机' },
        { label: '自动化评论', value: formatNumber(themes.reputation.automation_comments), note: '自动化披露信号，不构成 Momcozy 品牌机器人归因' },
        { label: '季度管理主张证据', value: formatNumber(themes.reputation.quarter_moderation_claim_evidence_count), note: '仅为审核白名单证据，不代表季度全部管理处置' },
      ],
      rankings: [{
        title: '风险信号量级',
        note: '不同信号口径不互斥；自动化评论、情感和严重度不得直接相互转化。',
        items: themes.reputation.rankings,
      }],
      evidence: themes.reputation.evidence,
      businessExplanation: [
        '负向与高严重度信号要求优先回到原帖复核事实、影响范围和处置状态，再决定是否进入危机流程。',
        '自动化评论只说明内容具备自动化披露特征；现有季度证据不支持确认品牌控制、机器人归属或商业关系。',
        '社区规范是业务约束：隐藏推广、批量自动回复或伪装用户身份会放大信任风险，建议采用透明披露与人工审批。',
      ],
      actions: [
        { priority: 'P0', title: '启动社区合规事实复核', detail: '联合核对账号、供应商、文案、披露方式和 subreddit 规则；确认前保持风险观察，不做品牌机器人归因。' },
        { priority: 'P1', title: '建立发布前人工门槛', detail: '对品牌相关回复、利益关系披露、重复文案和自动化工具建立发布前检查与留痕。' },
        { priority: 'P2', title: '监测风险复发', detail: '持续观察管理员处置、重复表达、高严重度负向和信任议题的复发，不以自动回复干预讨论。' },
      ],
      boundary: '自动化评论 ≠ 品牌机器人；管理员规则信号 ≠ 已确认品牌违规。所有行动均为待审批建议。',
    };
  }

  if (theme === 'new-product') {
    const topCategory = themes.new_product.category_rankings[0];
    const topFamily = themes.new_product.family_rankings[0];
    const topSpu = themes.new_product.exact_spu_rankings[0];
    return {
      ...common,
      artifactThemeId: 'new_product',
      managementQuestion: '哪些高频需求值得进入新品、迭代或体验验证，而不是直接被当成确定机会？',
      summary: `${topCategory.label}相关 VOC 为 ${formatNumber(topCategory.count)} 条；${topFamily.label}以 ${formatNumber(topFamily.count)} 条居产品家族首位。`,
      signals: [
        { label: '首要品类', value: formatNumber(topCategory.count), note: topCategory.label },
        { label: '首要产品家族', value: formatNumber(topFamily.count), note: topFamily.label },
        { label: '首要精确 SPU', value: formatNumber(topSpu.count), note: `${topSpu.label} · ${topSpu.id}` },
        { label: '洗瓶机品类 VOC', value: formatNumber(rankingValue(themes.new_product.category_rankings, 'bottle_washer')), note: '低量但具备明确使用与决策证据，需定性验证' },
      ],
      rankings: [
        { title: '品类议题', note: '按受治理品类事实去重 VOC。', items: themes.new_product.category_rankings },
        { title: '产品家族', note: '产品家族不等于精确 SPU。', items: themes.new_product.family_rankings },
        { title: '精确 SPU', note: '仅展示已通过精确 SPU 映射的结果。', items: themes.new_product.exact_spu_rankings },
      ],
      evidence: themes.new_product.evidence,
      businessExplanation: [
        '高频只代表讨论与问题机会的集中度，不能直接推导市场规模、销量或新品成功概率。',
        '建议把操作可靠性、适配舒适度与输出供给作为需求假设，结合品类和产品家族证据逐项验证。',
        `${themes.new_product.family_only_ids.length} 个受治理产品家族仍只具备家族级映射，页面不会把它们伪装为精确 SPU。`,
      ],
      actions: [
        { priority: 'P0', title: '建立需求假设清单', detail: '将高频痛点与品类、产品家族、精确 SPU 交叉，标记安全、可靠性和适配问题的验证责任人。' },
        { priority: 'P1', title: '开展场景验证', detail: '围绕吸奶器与洗瓶机的选择、使用、维护和适配场景，补充定性访谈或原帖追踪。' },
        { priority: 'P2', title: '形成验证后路线图', detail: '只有在证据、可行性和商业价值同时成立后，才进入新品、改款、说明优化或售后流程。' },
      ],
      boundary: '产品排序按已审核的产品事实对 VOC 去重统计；多标签结果不代表市场需求份额。',
    };
  }

  return {
    ...common,
    artifactThemeId: 'geo',
    managementQuestion: '如何把 Reddit 上的真实决策问题转成可信、可检索、可被生成式引擎引用的内容资产？',
    summary: `季度内识别 ${formatNumber(themes.geo.comparison_decision_posts)} 条 Momcozy 比较或决策帖子（竞品比较 ${formatNumber(rankingValue(themes.geo.rankings, 'competitor_comparison'))} 条、购买决策 ${formatNumber(rankingValue(themes.geo.rankings, 'purchase_decision'))} 条），下方品牌分布按帖子级竞品归属统计。`,
    signals: [
      { label: '比较与决策帖子', value: formatNumber(themes.geo.comparison_decision_posts), note: '按帖子级决策主题规则识别' },
      { label: '竞品比较问题', value: formatNumber(rankingValue(themes.geo.rankings, 'competitor_comparison')), note: '适合构建透明、可核查的对比回答' },
      { label: '购买决策问题', value: formatNumber(rankingValue(themes.geo.rankings, 'purchase_decision')), note: '适合构建适用人群、场景和限制说明' },
    ],
    rankings: [{
      title: '用户决策问题结构',
      note: '主题行按帖子级决策主题计数；品牌行按帖子-品牌对计数（一帖可提及多品牌），不是市场份额。',
      items: themes.geo.rankings,
    }],
    evidence: themes.geo.evidence,
    businessExplanation: [
      '竞品比较是最大的问题类型，内容应正面回答差异、适用人群、失败模式与限制，而不是只重复品牌卖点。',
      '高质量 GEO 资产必须保留证据来源、产品边界和品牌身份披露，才能同时服务用户决策、搜索检索和生成式引用。',
      '当前数据仅证明 Reddit 中存在相关问题，不证明页面已被 AI 引用、自然搜索提升或产生销售转化。',
    ],
    actions: [
      { priority: 'P0', title: '覆盖高频决策问题', detail: '为高频比较与购买问题建立直接答案，明确适用人群、关键差异、限制、故障排查和证据链接。' },
      { priority: 'P1', title: '建设可引用内容结构', detail: '将真实 Reddit 问题沉淀为对比页、FAQ、产品适配指南和售后知识，并采用清晰标题与结构化事实。' },
      { priority: 'P2', title: '建立问题覆盖监测', detail: '按季度复盘新问题、证据更新和内容缺口；禁止隐藏种草、批量灌水或伪装用户回复。' },
    ],
    boundary: 'GEO 主题来自帖子级比较与购买决策规则，不等同于关键词搜索量或 AI 引用效果。',
  };
}

function ScopeMetric({ label, note, value }: ThemeSignal) {
  return (
    <div className="rounded-[18px] border border-white/70 bg-white/80 p-4 shadow-sm backdrop-blur-sm">
      <p className="text-[26px] font-semibold tracking-tight text-foreground">{value}</p>
      <p className="mt-1 text-caption font-semibold text-foreground">{label}</p>
      <p className="mt-1 text-tiny leading-relaxed text-foreground-muted">{note}</p>
    </div>
  );
}

function RankingBars({ group }: { group: RankingGroup }) {
  const max = Math.max(...group.items.map((item) => item.count), 1);
  return (
    <div className="rounded-[22px] border border-border-divider bg-white p-5 shadow-card" data-testid="theme-ranking-group">
      <h4 className="text-body-sm font-semibold text-foreground">{group.title}</h4>
      <p className="mt-1 text-tiny leading-relaxed text-foreground-muted">{group.note}</p>
      <div className="mt-4 space-y-3" role="list" aria-label={group.title}>
        {group.items.map((item) => (
          <div key={item.id} role="listitem" data-ranking-id={item.id}>
            <div className="mb-1.5 flex items-center justify-between gap-3 text-caption">
              <span className="font-medium text-foreground-secondary">{item.label}</span>
              <span className="shrink-0 tabular-nums font-semibold text-foreground">{formatNumber(item.count)}</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-surface-tertiary">
              <div
                className="h-full rounded-full bg-gradient-to-r from-primary via-[#31A77E] to-[#F3A16B]"
                style={{ width: `${Math.max((item.count / max) * 100, 2)}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function StorySection({
  children,
  icon: Icon,
  index,
  title,
}: {
  children: ReactNode;
  icon: LucideIcon;
  index: string;
  title: string;
}) {
  return (
    <section className="rounded-[24px] border border-border-divider bg-white p-5 shadow-card sm:p-6" data-story-section={index} aria-labelledby={`story-section-${index}`}>
      <div className="flex items-center gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-icon bg-primary-light text-primary">
          <Icon className="h-[18px] w-[18px]" strokeWidth={1.5} aria-hidden="true" />
        </span>
        <div>
          <p className="font-mono text-tiny font-semibold text-primary-hover">{index}</p>
          <h3 id={`story-section-${index}`} className="text-h3 text-foreground">{title}</h3>
        </div>
      </div>
      <div className="mt-5">{children}</div>
    </section>
  );
}

function EvidenceList({
  evidence,
  releaseId,
  snapshotId,
}: {
  evidence: QuarterInsightEvidence[];
  releaseId: string;
  snapshotId: string;
}) {
  return (
    <div className="grid gap-3 lg:grid-cols-2" role="list" aria-label="Reddit 原始证据">
      {evidence.map((item, index) => (
        <Link
          key={`${item.post_id}:${item.comment_id ?? 'post'}`}
          role="listitem"
          className="group flex items-start gap-3 rounded-[18px] border border-border-divider bg-surface-tertiary/55 p-4 transition-colors hover:border-primary/25 hover:bg-primary-light/35"
          to={buildSnapshotEvidenceHref({
            postId: item.post_id,
            commentId: item.comment_id,
            releaseId,
            snapshotId,
            source: 'insights',
          })}
        >
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-white text-tiny font-semibold text-primary shadow-sm">{index + 1}</span>
          <span className="min-w-0 flex-1">
            <span className="block text-caption font-semibold leading-relaxed text-foreground">{EVIDENCE_REASON_LABELS[item.reason] ?? item.reason}</span>
            <span className="mt-1 block font-mono text-tiny text-foreground-muted">
              帖子编号 {item.post_id}{item.comment_id ? ` · 评论编号 ${item.comment_id}` : ''}
            </span>
          </span>
          <Search className="mt-1 h-4 w-4 shrink-0 text-foreground-muted transition-colors group-hover:text-primary" strokeWidth={1.5} aria-hidden="true" />
        </Link>
      ))}
    </div>
  );
}

function ActionPlan({ actions }: { actions: ThemeAction[] }) {
  const priorityStyle: Record<Priority, string> = {
    P0: 'border-[#EA6B65]/25 bg-[#FFF2F1] text-[#B73E39]',
    P1: 'border-[#EEA35A]/25 bg-[#FFF8EE] text-[#A85B13]',
    P2: 'border-primary/20 bg-primary-light/45 text-primary-hover',
  };
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      {actions.map((action) => (
        <article key={action.priority} className="rounded-[20px] border border-border-divider bg-surface-tertiary/35 p-4">
          <span className={`inline-flex rounded-badge border px-2.5 py-1 text-tiny font-semibold ${priorityStyle[action.priority]}`}>
            {action.priority}
          </span>
          <h4 className="mt-3 text-body-sm font-semibold text-foreground">{action.title}</h4>
          <p className="mt-2 text-caption leading-relaxed text-foreground-secondary">{action.detail}</p>
        </article>
      ))}
    </div>
  );
}

function CaseMethodReference({
  artifactThemeId,
  casebookState,
  quarterInsights,
}: {
  artifactThemeId: ArtifactThemeId;
  casebookState: SnapshotInsightsV3Props['casebookState'];
  quarterInsights: RedditQuarterInsightsData;
}) {
  const reference = quarterInsights.case_references[artifactThemeId];
  if (reference.id === null) {
    return (
      <div className="rounded-[18px] border border-dashed border-border-divider bg-surface-tertiary/55 p-5">
        <p className="text-body-sm font-semibold text-foreground">暂无已审核案例方法参照</p>
        <p className="mt-2 text-caption leading-relaxed text-foreground-secondary">
          本模块只呈现本季度 Reddit 证据与待验证建议，不用演示案例或未审核案例补位。
        </p>
        <Link
          className="mt-3 inline-flex items-center gap-1 text-caption font-semibold text-primary hover:underline"
          to="/cases"
        >
          浏览案例广场候选方法 <ArrowRight className="h-4 w-4" strokeWidth={1.5} aria-hidden="true" />
        </Link>
        <p className="mt-2 text-tiny leading-relaxed text-foreground-muted">案例广场候选内容独立浏览，不参与本模块排序、结论或成效证明。</p>
      </div>
    );
  }
  if (casebookState.isLoading) {
    return <div className="rounded-[18px] bg-surface-tertiary p-5 text-caption text-foreground-muted">正在加载已审核案例方法参照…</div>;
  }
  const dossier = casebookState.data?.data.dossiers.find((item) => item.case_id === reference.id) ?? null;
  if (casebookState.error || !dossier) {
    return (
      <div className="rounded-[18px] border border-[#EEA35A]/25 bg-[#FFF8EE] p-5">
        <p className="text-body-sm font-semibold text-foreground">已审核案例方法参照暂不可用</p>
        <p className="mt-2 text-caption text-foreground-secondary">{casebookState.error ?? '季度产物引用的案例尚未加载'}；不影响本季度 Reddit 核心信号。</p>
      </div>
    );
  }
  return (
    <div className="rounded-[20px] border border-[#EEA35A]/25 bg-gradient-to-br from-[#FFF9EF] to-white p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <span className="rounded-badge bg-white px-2.5 py-1 text-tiny font-semibold text-[#A85B13] shadow-sm">历史治理方法参照</span>
          <h4 className="mt-3 text-body-sm font-semibold text-foreground">{dossier.title}</h4>
          <p className="mt-2 max-w-3xl text-caption leading-relaxed text-foreground-secondary">{dossier.business_question}</p>
        </div>
        <Link
          className="inline-flex items-center gap-1 text-caption font-semibold text-primary hover:underline"
          to={`/cases?view=operations&case=${reference.id}`}
        >
          查看案例方法 <ArrowRight className="h-4 w-4" strokeWidth={1.5} aria-hidden="true" />
        </Link>
      </div>
      <div className="mt-4 rounded-card border border-[#EEA35A]/20 bg-white/80 p-3 text-tiny leading-relaxed text-[#77501D]">
        仅借鉴“洞察—证据—行动—监测—复盘”的治理方法；历史案例不构成本季度信号证据，也不确认品牌机器人归属。
      </div>
    </div>
  );
}

export interface SnapshotInsightsV3Props {
  snapshot: V3RedditInsightsSnapshot;
  baseSnapshot: RedditSnapshotCore;
  quarterInsights: RedditQuarterInsightsData;
  personasState: PersonasState;
  casebookState: {
    data: RedditPublicCasebook | null;
    error: string | null;
    isLoading: boolean;
  };
}

export default function SnapshotInsightsV3({
  baseSnapshot,
  quarterInsights,
  personasState,
  casebookState,
}: SnapshotInsightsV3Props) {
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedTheme = searchParams.get('theme');
  const activeTheme: ThemeId = themeOrder.includes(requestedTheme as ThemeId)
    ? requestedTheme as ThemeId
    : 'pain';
  const model = buildThemeViewModel(activeTheme, quarterInsights);
  const analysisVocs = quarterInsights.counts.analysis_post_vocs + quarterInsights.counts.analysis_comment_context_vocs;
  const periodLabel = `最近一个季度（${quarterInsights.period.start_date} 至 ${quarterInsights.period.end_date}）`;
  const totalUnresolvedParentComments = baseSnapshot.manifest.schema_version === 'reddit_voc_site_snapshot_manifest_v3'
    ? baseSnapshot.manifest.canonical_counts.unresolved_parent_comments ?? 0
    : null;
  const quarterPersonaScope = {
    assignmentIds: quarterInsights.personas.main_assignment_ids,
    categoryAssignments: quarterInsights.personas.category_context_assignment_count,
    categoryEntities: quarterInsights.personas.category_context_unique_entities,
  };
  // The persona snapshot is a frozen artifact whose assignment id namespace is
  // disjoint from the quarter's live ids, so filtering its rows by the quarter
  // allowlist yields zero for every cohort. Pass the quarter's own per-cohort
  // counts down as the authoritative distribution, plus its declared denominator
  // so the panel can refuse to print 100.00% over a partial sum.
  const quarterCohortAssignmentCounts: Record<string, number> = Object.fromEntries(
    quarterInsights.personas.cohorts.map((cohort) => [cohort.cohort_id, cohort.assignment_count]),
  );
  const quarterDeclaredMainAssignmentCount = quarterInsights.personas.main_assignment_count;

  const selectTheme = (theme: ThemeId) => {
    const next = new URLSearchParams(searchParams);
    next.set('theme', theme);
    setSearchParams(next);
  };

  const handleTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>, theme: ThemeId) => {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
    event.preventDefault();
    const currentIndex = themeOrder.indexOf(theme);
    const offset = event.key === 'ArrowRight' ? 1 : -1;
    const nextTheme = themeOrder[(currentIndex + offset + themeOrder.length) % themeOrder.length];
    selectTheme(nextTheme);
    document.getElementById(`insight-theme-tab-${nextTheme}`)?.focus();
  };

  return (
    <SnapshotPageLayout
      icon={Lightbulb}
      title="Momcozy Reddit VOC 洞察"
      description="最近滚动季度 · 用户画像 · 用户痛点 · 舆情与内容合规 · 新品机会 · GEO 优化"
      datasetVersion={quarterInsights.dataset_version}
      freshness={createBaseDataFreshness(baseSnapshot, {
        projectionAsOfLabel: '洞察覆盖截至',
        projectionAsOf: quarterInsights.period.end_date,
        projectionAsOfBasis: '来自季度正式投影 period.end_date，不等同于采集任务完成时间',
        projectionDatasetVersion: quarterInsights.dataset_version,
        projectionGeneratedAtUtc: quarterInsights.generated_at_utc,
        coverageWindowStart: quarterInsights.period.start_date,
        coverageWindowEnd: quarterInsights.period.end_date,
      })}
    >
      <section
        className="overflow-hidden rounded-[26px] border border-primary/15 bg-gradient-to-br from-primary-light/75 via-white to-[#FFF4EA] p-5 shadow-card sm:p-7"
        data-governance-component="data-scope-bar"
        data-insight-story-step="scope"
        aria-labelledby="quarter-scope-title"
        {...crossPageReconciliationAttributes({
          page: 'insights',
          sourceSnapshotId: quarterInsights.source.source_snapshot_id,
          scope: 'momcozy',
          vocType: 'post_voc+comment_context_voc',
          startDate: quarterInsights.period.start_date,
          endDate: quarterInsights.period.end_date,
          endBoundary: 'inclusive',
        })}
      >
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 text-primary-hover">
              <CalendarRange className="h-5 w-5" strokeWidth={1.5} aria-hidden="true" />
              <h2 id="quarter-scope-title" className="text-h2 text-foreground">最近一个季度 · 数据口径</h2>
            </div>
            <p className="mt-2 max-w-4xl text-caption leading-relaxed text-foreground-secondary">
              {quarterInsights.period.start_date} 至 {quarterInsights.period.end_date}，共 {quarterInsights.period.days} 个自然日，按 {quarterInsights.period.timezone} 的内容实体事件日期统计；首尾日期均纳入。
            </p>
            <p className="mt-2 max-w-4xl text-tiny leading-relaxed text-foreground-muted">
              {CROSS_PAGE_RECONCILIATION_RULE_CN} 当前为滚动季度窗口。
            </p>
          </div>
          <span className="inline-flex items-center gap-2 rounded-badge border border-primary/15 bg-white px-3 py-1.5 text-tiny font-semibold text-primary-hover shadow-sm">
            <ShieldCheck className="h-3.5 w-3.5" strokeWidth={1.5} aria-hidden="true" />
            Reddit 观察样本 · Momcozy 为分析主干
          </span>
        </div>

        <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4" data-testid="quarter-scope-metrics">
          <ScopeMetric label="观察帖子" value={formatNumber(quarterInsights.counts.canonical_posts)} note="季度规范帖子总量" />
          <ScopeMetric label="周期评论" value={formatNumber(quarterInsights.counts.periodic_comments)} note={`${formatNumber(quarterInsights.counts.linked_comment_context_vocs)} 条已关联为评论上下文 VOC`} />
          <ScopeMetric label="分析池 VOC" value={formatNumber(analysisVocs)} note={`${formatNumber(quarterInsights.counts.analysis_post_vocs)} 帖子 VOC + ${formatNumber(quarterInsights.counts.analysis_comment_context_vocs)} 评论上下文 VOC`} />
          <ScopeMetric label="Momcozy VOC" value={formatNumber(quarterInsights.counts.momcozy.total_vocs)} note={`${formatNumber(quarterInsights.counts.momcozy.post_vocs)} 帖子 VOC + ${formatNumber(quarterInsights.counts.momcozy.comment_context_vocs)} 评论上下文 VOC`} />
        </div>

        <div className="mt-4 grid gap-3 text-tiny leading-relaxed text-foreground-secondary lg:grid-cols-3">
          <p className="rounded-card bg-white/65 p-3"><strong className="text-foreground">情感：</strong>负向占比 {quarterInsights.counts.momcozy.sentiment.negative_rate.toFixed(2)}% = {formatNumber(quarterInsights.counts.momcozy.sentiment.negative)} / {formatNumber(quarterInsights.counts.momcozy.sentiment.classified)} 条已分类 VOC；另有 {formatNumber(quarterInsights.counts.momcozy.sentiment.missing)} 条情感缺失。</p>
          <p className="rounded-card bg-white/65 p-3"><strong className="text-foreground">竞品：</strong>竞品并集 {formatNumber(quarterInsights.counts.competitor_union_vocs)} 条，与 Momcozy 重叠 {formatNumber(quarterInsights.counts.momcozy_competitor_overlap_vocs)} 条；集合不互斥，不解释为市场份额。</p>
          <p className="rounded-card bg-white/65 p-3"><strong className="text-foreground">结构债务：</strong>{formatNumber(quarterInsights.counts.unresolved_parent_comments)} 条评论在本季度仍缺少可关联父帖，未进入已关联评论上下文 VOC。{totalUnresolvedParentComments === null ? '' : `全站待关联评论共 ${formatNumber(totalUnresolvedParentComments)} 条。`}</p>
        </div>
      </section>

      <div id="user-personas" className="scroll-mt-24" data-insight-story-step="personas">
        <AggregatePersonaPanel
          {...personasState}
          assignmentIds={quarterPersonaScope.assignmentIds}
          periodLabel={periodLabel}
          categoryContextAssignmentCount={quarterPersonaScope.categoryAssignments}
          categoryContextUniqueEntityCount={quarterPersonaScope.categoryEntities}
          cohortAssignmentCounts={quarterCohortAssignmentCounts}
          declaredMainAssignmentCount={quarterDeclaredMainAssignmentCount}
        />
      </div>

      <section className="rounded-[26px] border border-primary/15 bg-white p-5 shadow-card sm:p-7" data-insight-story-step="themes" aria-labelledby="quarter-story-title">
        <div className="grid gap-5 lg:grid-cols-[1.25fr_0.75fr] lg:items-center">
          <div>
            <span className="inline-flex items-center gap-2 rounded-badge bg-primary-light px-3 py-1.5 text-tiny font-semibold text-primary-hover">
              <Sparkles className="h-3.5 w-3.5" strokeWidth={1.5} aria-hidden="true" />
              从 Reddit 证据到业务动作
            </span>
            <h2 id="quarter-story-title" className="mt-4 max-w-3xl text-[28px] font-semibold leading-tight tracking-[-0.025em] text-foreground sm:text-[36px]">
              先看谁在讨论，再回答哪里需要改、哪里值得做、内容如何建立信任。
            </h2>
            <p className="mt-3 max-w-3xl text-body-sm leading-relaxed text-foreground-secondary">
              四个模块统一采用同一最近季度和同一 Momcozy 受治理分析范围；其他品牌只作为同一 Reddit 样本中的对比语境。
            </p>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-[18px] border border-primary/15 bg-primary-light/45 p-4">
              <UsersRound className="h-5 w-5 text-primary" strokeWidth={1.5} aria-hidden="true" />
              <p className="mt-3 text-[24px] font-semibold text-foreground">{formatNumber(quarterInsights.personas.main_assignment_count)}</p>
              <p className="mt-1 text-tiny text-foreground-muted">Momcozy 内容画像赋值</p>
            </div>
            <div className="rounded-[18px] border border-[#EEA35A]/20 bg-[#FFF8EE] p-4">
              <MessageSquareText className="h-5 w-5 text-[#B66A20]" strokeWidth={1.5} aria-hidden="true" />
              <p className="mt-3 text-[24px] font-semibold text-foreground">{formatNumber(quarterInsights.counts.momcozy.total_vocs)}</p>
              <p className="mt-1 text-tiny text-foreground-muted">Momcozy 季度 VOC</p>
            </div>
          </div>
        </div>

        <div className="mt-6 grid gap-2 rounded-[20px] bg-surface-tertiary/75 p-2 sm:grid-cols-2 xl:grid-cols-4" role="tablist" aria-label="季度洞察主题">
          {themeOrder.map((theme) => {
            const Icon = themeMeta[theme].icon;
            const selected = activeTheme === theme;
            return (
              <button
                key={theme}
                id={`insight-theme-tab-${theme}`}
                type="button"
                role="tab"
                aria-selected={selected}
                aria-controls="quarter-theme-panel"
                tabIndex={selected ? 0 : -1}
                className={`rounded-[16px] border px-4 py-3 text-left transition-all ${selected ? 'border-primary/15 bg-white text-foreground shadow-sm' : 'border-transparent text-foreground-muted hover:bg-white/65 hover:text-foreground'}`}
                onClick={() => selectTheme(theme)}
                onKeyDown={(event) => handleTabKeyDown(event, theme)}
              >
                <span className="flex items-center gap-2 text-caption font-semibold">
                  <Icon className={`h-4 w-4 ${selected ? 'text-primary' : ''}`} strokeWidth={1.5} aria-hidden="true" />
                  {themeMeta[theme].label}
                </span>
                <span className="mt-1 block text-tiny font-normal text-foreground-muted">{themeMeta[theme].shortLabel}</span>
              </button>
            );
          })}
        </div>
      </section>

      <div
        id="quarter-theme-panel"
        role="tabpanel"
        aria-labelledby={`insight-theme-tab-${activeTheme}`}
        data-theme={activeTheme}
        className="space-y-5"
      >
        <section className="overflow-hidden rounded-[26px] border border-primary/15 bg-gradient-to-r from-primary-light/65 via-white to-[#FFF7EE] p-5 shadow-card sm:p-7" aria-labelledby="management-question-title">
          <div className="flex items-start gap-4">
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-icon bg-white text-primary shadow-sm">
              <model.icon className="h-5 w-5" strokeWidth={1.5} aria-hidden="true" />
            </span>
            <div>
              <p className="text-tiny font-semibold uppercase tracking-[0.12em] text-primary-hover">管理问题</p>
              <h2 id="management-question-title" className="mt-2 text-h2 leading-snug text-foreground">{model.managementQuestion}</h2>
              <p className="mt-3 max-w-4xl text-body-sm leading-relaxed text-foreground-secondary">{model.summary}</p>
            </div>
          </div>
        </section>

        <StorySection index="01" title="核心信号" icon={Target}>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {model.signals.map((signal) => <ScopeMetric key={signal.label} {...signal} />)}
          </div>
          <div className={`mt-4 grid gap-4 ${model.rankings.length > 1 ? 'xl:grid-cols-3' : ''}`}>
            {model.rankings.map((group) => <RankingBars key={group.title} group={group} />)}
          </div>
          <div className="mt-4 flex items-start gap-2 rounded-[16px] border border-primary/10 bg-primary-light/35 p-3 text-tiny leading-relaxed text-foreground-secondary">
            <CircleHelp className="mt-0.5 h-4 w-4 shrink-0 text-primary" strokeWidth={1.5} aria-hidden="true" />
            {model.boundary}
          </div>
        </StorySection>

        <StorySection index="02" title="Reddit 证据" icon={GalleryVerticalEnd}>
          <EvidenceList
            evidence={model.evidence}
            releaseId={baseSnapshot.release.release_id}
            snapshotId={baseSnapshot.manifest.dataset_version}
          />
          <p className="mt-3 text-tiny leading-relaxed text-foreground-muted">证据标题来自季度公开投影的审核理由；点击进入站内原帖/评论定位，不在洞察页暴露作者身份或原始正文。</p>
        </StorySection>

        <StorySection index="03" title="业务解释" icon={Lightbulb}>
          <div className="grid gap-3 lg:grid-cols-3">
            {model.businessExplanation.map((item, index) => (
              <article key={item} className="rounded-[18px] border border-border-divider bg-surface-tertiary/45 p-4">
                <span className="font-mono text-tiny font-semibold text-primary">0{index + 1}</span>
                <p className="mt-2 text-caption leading-relaxed text-foreground-secondary">{item}</p>
              </article>
            ))}
          </div>
        </StorySection>

        <StorySection index="04" title="P0 / P1 / P2 建议" icon={CheckCircle2}>
          <ActionPlan actions={model.actions} />
          <p className="mt-4 text-tiny leading-relaxed text-foreground-muted">建议仅供业务审批和任务拆解，不表示已经回复 Reddit 用户、执行推广、修改数据或完成整改。</p>
        </StorySection>

        <StorySection index="05" title="案例方法参照" icon={GalleryVerticalEnd}>
          <CaseMethodReference
            artifactThemeId={model.artifactThemeId}
            casebookState={casebookState}
            quarterInsights={quarterInsights}
          />
        </StorySection>

        {activeTheme === 'reputation' && (
          <section className="rounded-[20px] border border-[#EA6B65]/20 bg-[#FFF4F2] p-4" aria-label="内容合规归因边界">
            <div className="flex items-start gap-3">
              <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-[#C6534D]" strokeWidth={1.5} aria-hidden="true" />
              <div>
                <p className="text-body-sm font-semibold text-foreground">归因红线</p>
                <p className="mt-1 text-caption leading-relaxed text-foreground-secondary">本季度自动化评论与管理员规则证据不支持确认 Momcozy 使用机器人、控制相关账号或存在商业关系；页面只表达风险观察与复核建议。</p>
              </div>
            </div>
          </section>
        )}
      </div>
    </SnapshotPageLayout>
  );
}
