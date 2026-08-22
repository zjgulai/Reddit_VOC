import { useEffect, useState } from 'react';
import { Calendar, FileText, RefreshCw } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import ExportButton from '../components/ExportButton';
import type { ExportSection } from '../components/ExportButton';
import RealReportView from '../components/reports/RealReportView';
import {
  CROSS_PAGE_RECONCILIATION_RULE_CN,
  crossPageReconciliationAttributes,
} from '../features/redditSnapshot/crossPageReconciliation';
import { createBaseDataFreshness } from '../features/redditSnapshot/freshness';
import { isDisplayableReportIndicator } from '../components/reports/reportIndicatorPresentation';
import {
  SnapshotErrorPage,
  SnapshotLoadingPage,
  SnapshotPageLayout,
} from '../features/redditSnapshot/SnapshotPageLayout';
import { formatDateTime, formatTopic, SENTIMENT_LABELS } from '../features/redditSnapshot/format';
import {
  createReportGovernanceContract,
  createV3ReportGovernanceContract,
  DataScopeBar,
} from '../features/redditSnapshot/governance';
import type {
  DisplayableRedditReport,
  ReportPeriod,
  V3CurrentReport,
} from '../features/redditSnapshot/reports';
import {
  isRiskReport,
  isV3Report,
  isV3ReportsSnapshot,
  loadV3HistoricalReport,
} from '../features/redditSnapshot/reports';
import { useRedditReports } from '../features/redditSnapshot/useRedditReports';
import { useRedditSnapshot } from '../features/redditSnapshot/useRedditSnapshot';

const tabConfig: Record<ReportPeriod, { label: string; description: string }> = {
  daily: { label: '日报', description: '即时止损 · 下一步行动' },
  weekly: { label: '周报', description: '趋势诊断 · 下周计划' },
  monthly: { label: '月报', description: '品牌复盘 · 战略建议' },
};

export function buildV3ExportSections(report: V3CurrentReport): ExportSection[] {
  const coverageLabel = report.comparison_contract_proven
    ? `数据所有者确认完整性 ${report.completeness_percent}%`
    : '日历周期已闭合；历史采集覆盖未获完整性证明，禁止同环比与趋势结论';
  const sections: ExportSection[] = [
    {
      title: '报告周期与数据边界',
      subtitle: `${coverageLabel}；指标按统一口径预先计算`,
      headers: ['字段', '值'],
      rows: [
        ['业务入口', report.entry_label],
        ['周期粒度', report.grain],
        ['周期开始', report.period.start],
        ['周期结束（不含）', report.period.end],
        ['周期 ID', report.period.period_id],
        ['覆盖完整性', report.comparison_contract_proven ? `${report.completeness_percent}%` : '未证明'],
        ['数据使用边界', '版本化只读快照；页面不会触发外部服务、改写业务数据或发送通知'],
      ],
    },
    {
      title: 'Momcozy 指标同环比与趋势',
      subtitle: '只导出真实可计算的标量指标；环比、同比或趋势不可计算时不输出该比较项',
      headers: ['指标 ID', '指标', '当前值', '状态', '环比', '同比', '趋势'],
      rows: report.indicators.filter(isDisplayableReportIndicator).map((indicator) => [
        indicator.metric_id,
        indicator.name_cn,
        indicator.current.display,
        indicator.current.status,
        indicator.comparisons.period_over_period.status === 'unavailable' ? '' : indicator.comparisons.period_over_period.display,
        indicator.comparisons.year_over_year.status === 'unavailable' ? '' : indicator.comparisons.year_over_year.display,
        indicator.sparkline.status === 'unavailable' ? '' : indicator.sparkline.direction ?? '',
      ]),
    },
  ];
  if (report.grain === 'monthly') {
    sections.push({
      title: '品牌健康四维构成',
      subtitle: '治理后有机口径；维度分由帖子与评论各 50% 合成，指数构成贡献 = 维度分 × 25%',
      headers: ['维度', '维度分', '权重', '对总指数贡献', '状态'],
      rows: report.brand_health.dimension_rows
        .filter((row) => row.comparison_side === 'qualified_organic' && row.status !== 'unavailable')
        .map((row) => [
          row.dimension_id,
          row.dimension_value ?? '',
          `${row.weight_percent}%`,
          row.contribution_points ?? '',
          row.status,
        ]),
    });
  }
  if (report.grain === 'weekly' && report.action_review) {
    sections.push({
      title: '行动复盘状态',
      subtitle: '建议行动不等同于执行记录；没有真实账本时不计算完成率',
      headers: ['状态', '账本可用', '支持完成率', '原因'],
      rows: [[
        report.action_review.status,
        report.action_review.ledger_available ? '是' : '否',
        report.action_review.completion_supported ? '是' : '否',
        report.action_review.reason_codes.join(' · '),
      ]],
    });
  }
  return sections;
}

function buildExportSections(report: DisplayableRedditReport): ExportSection[] {
  if (isV3Report(report)) return buildV3ExportSections(report);
  if (isRiskReport(report)) {
    const comparisonRows = (['previous_period', 'year_over_year'] as const).flatMap((comparisonPeriod) =>
      (['post', 'comment'] as const).flatMap((entityType) => {
        const count = report.observed_count_comparisons[comparisonPeriod][entityType];
        const negative = report.period_comparisons[comparisonPeriod][entityType];
        return [
          [comparisonPeriod, entityType, 'observed_count', count.comparison_status, count.current.value ?? '—', count.baseline?.value ?? '—', count.absolute_delta ?? '—', count.reason_codes.join(' · ')],
          [comparisonPeriod, entityType, 'negative_evidence_share', negative.comparison_status, negative.current.value ?? '—', negative.baseline?.value ?? '—', negative.absolute_delta ?? '—', negative.reason_codes.join(' · ')],
        ];
      }),
    );
    const productRows = (['category', 'product_family', 'spu_exact'] as const).flatMap((level) =>
      report.product_period_analysis[level].flatMap((row) =>
        (['post', 'comment'] as const).map((entityType) => [
          level,
          row.scope_id,
          row.scope_name_cn || row.scope_name_en,
          entityType,
          row.current[entityType].observed_count.value ?? '—',
          row.current[entityType].negative_evidence_share.value ?? '—',
          row.period_comparisons.previous_period[entityType].negative_evidence_share.comparison_status,
          row.period_comparisons.year_over_year[entityType].negative_evidence_share.comparison_status,
          row.trend.direction_claim_supported ? 'supported' : 'observations_only',
        ]),
      ),
    );
    return [
      {
        title: '报告周期与数据边界',
        subtitle: 'Momcozy 为主干；帖子和评论分开；空值保留原因',
        headers: ['字段', '值'],
        rows: [
          ['报告', report.identity.display_name],
          ['窗口开始', report.window.start_local],
          ['窗口结束', report.window.end_local],
          ['覆盖状态', report.window.coverage_status],
          ['比较状态', report.window.comparison_status],
          ['数据使用边界', '版本化只读快照；页面不会触发外部服务、改写业务数据或发送通知'],
        ],
      },
      {
        title: 'Momcozy 本期指标',
        headers: ['实体', '观察量', '负面分子', '负面分母', '负面占比'],
        rows: (['post', 'comment'] as const).map((entityType) => {
          const observed = report.momcozy_metrics.observed_count[entityType];
          const negative = report.momcozy_metrics.negative_evidence_share[entityType];
          return [entityType, observed.value ?? '—', negative.numerator ?? '—', negative.denominator ?? '—', negative.value ?? '—'];
        }),
      },
      {
        title: '环比与同比',
        headers: ['比较', '实体', '指标', '状态', '当前', '基期', '绝对差值', '原因'],
        rows: comparisonRows,
      },
      {
        title: '风险主题',
        subtitle: '仅导出公开字段与证据 ID，不包含内部行动建议',
        headers: ['主题 ID', '名称', '优先级', '门禁', '帖子', '评论', '品类', '产品族', 'SPU', '证据 ID'],
        rows: report.risk_themes.map((theme) => [
          theme.risk_theme_id,
          theme.name_cn,
          theme.effective_priority,
          theme.evidence_gate.status,
          theme.observed_entities.post,
          theme.observed_entities.comment,
          theme.product_scope_ids.category.join(' | '),
          theme.product_scope_ids.product_family.join(' | '),
          theme.product_scope_ids.spu_exact.join(' | '),
          theme.evidence_refs.map((evidence) => `${evidence.entity_type}:${evidence.entity_id}`).join(' | '),
        ]),
      },
      {
        title: '产品三层周期分析',
        headers: ['层级', '范围 ID', '名称', '实体', '观察量', '负面占比', '环比状态', '同比状态', '趋势方向门禁'],
        rows: productRows,
      },
    ];
  }
  return [
    {
      title: '窗口与数据边界',
      subtitle: '采集覆盖未验证；不得解释为市场趋势',
      headers: ['字段', '值'],
      rows: [
        ['报告', report.identity.display_name],
        ['窗口开始', report.window.start_local],
        ['窗口结束', report.window.end_local],
        ['覆盖状态', report.window.coverage_status],
        ['比较状态', report.window.comparison_status],
        ['页面状态', '已验证的只读数据版本'],
        ['外部影响', '页面浏览与导出不会触发采集、写入或通知'],
      ],
    },
    {
      title: '已观察概览',
      headers: ['指标', '数值'],
      rows: [
        ['帖子', report.headline.posts],
        ['VOC 评论', report.headline.voc_comments],
        ['帖子负面', report.headline.post_sentiment.counts.negative],
        ['评论负面', report.headline.comment_sentiment.counts.negative],
        ['关注项', report.attention_items.length],
      ],
    },
    {
      title: '社区分布',
      headers: ['社区', '帖子', 'VOC 评论', '已观察实体'],
      rows: report.communities.map((row) => [row.subreddit, row.posts, row.voc_comments, row.observed_entities]),
    },
    {
      title: '品牌样本提及',
      subtitle: '不是市场份额；多品牌帖子可重复计数',
      headers: ['品牌', '提及帖子', '帖子分母'],
      rows: report.brand_mentions.map((row) => [row.brand, row.sample_mention_posts, row.sample_mention_share.denominator]),
    },
    {
      title: '证据帖子',
      headers: ['标题', '社区', '主题', '情感', '创建时间', 'Reddit 链接'],
      rows: report.evidence_posts.map((row) => [row.title, row.subreddit, formatTopic(row.topic), SENTIMENT_LABELS[row.sentiment], row.created_at_utc, row.permalink]),
    },
  ];
}

function v3PeriodRange(report: V3CurrentReport): string {
  if (report.grain === 'daily') return report.period.start;
  if (report.grain === 'monthly') return report.period.start.slice(0, 7);
  const exclusiveEnd = Date.parse(`${report.period.end}T00:00:00Z`);
  const inclusiveEnd = new Date(exclusiveEnd - 86_400_000).toISOString().slice(0, 10);
  return `${report.period.start} 至 ${inclusiveEnd}`;
}

function currentPeriodLabel(period: ReportPeriod, report: DisplayableRedditReport): string {
  if (isV3Report(report)) {
    if (period === 'daily') return `${report.period.start} 完整自然日`;
    if (period === 'monthly') return `${report.period.start.slice(0, 7)} 完整自然月`;
    const exclusiveEnd = Date.parse(`${report.period.end}T00:00:00Z`);
    const inclusiveEnd = new Date(exclusiveEnd - 86_400_000).toISOString().slice(0, 10);
    return `${report.period.start} 至 ${inclusiveEnd} 完整自然周`;
  }
  return report.identity.display_name;
}

function historyPeriodLabel(period: ReportPeriod, entry: { period: V3CurrentReport['period'] }): string {
  if (period === 'daily') return entry.period.start;
  if (period === 'monthly') return entry.period.start.slice(0, 7);
  const exclusiveEnd = Date.parse(`${entry.period.end}T00:00:00Z`);
  const inclusiveEnd = new Date(exclusiveEnd - 86_400_000).toISOString().slice(0, 10);
  return `${entry.period.start} 至 ${inclusiveEnd}`;
}

export default function SnapshotReports() {
  const { data, error, isLoading, isReloading, reload } = useRedditReports();
  const base = useRedditSnapshot();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedPeriod = searchParams.get('period');
  const requestedPeriodId = searchParams.get('period_id');
  const captureMode = searchParams.get('capture') === 'poster';
  const invalidRequestedPeriod = requestedPeriod !== null
    && requestedPeriod !== 'daily'
    && requestedPeriod !== 'weekly'
    && requestedPeriod !== 'monthly';
  const period: ReportPeriod = requestedPeriod === 'weekly' || requestedPeriod === 'monthly'
    ? requestedPeriod
    : 'daily';
  const setPeriod = (nextPeriod: ReportPeriod) => {
    const next = new URLSearchParams(searchParams);
    next.set('period', nextPeriod);
    next.delete('period_id');
    setSearchParams(next, { replace: true });
  };
  const [historicalReport, setHistoricalReport] = useState<V3CurrentReport | null>(null);
  const [historicalError, setHistoricalError] = useState<string | null>(null);
  const [isHistoricalLoading, setIsHistoricalLoading] = useState(false);

  useEffect(() => {
    let active = true;
    if (!data || !isV3ReportsSnapshot(data) || !requestedPeriodId) {
      setHistoricalReport(null);
      setHistoricalError(null);
      setIsHistoricalLoading(false);
      return () => { active = false; };
    }
    const exists = data.historyIndex?.reports[period].some(
      (entry) => entry.period.period_id === requestedPeriodId,
    );
    if (!exists) {
      setHistoricalReport(null);
      setHistoricalError('该历史周期不属于当前数据版本，请重新选择。');
      setIsHistoricalLoading(false);
      return () => { active = false; };
    }
    setHistoricalReport(null);
    setHistoricalError(null);
    setIsHistoricalLoading(true);
    void loadV3HistoricalReport(data, period, requestedPeriodId)
      .then((report) => {
        if (active) setHistoricalReport(report);
      })
      .catch((loadError: unknown) => {
        if (active) {
          setHistoricalError(loadError instanceof Error ? loadError.message : '历史报告加载失败');
        }
      })
      .finally(() => {
        if (active) setIsHistoricalLoading(false);
      });
    return () => { active = false; };
  }, [data, period, requestedPeriodId]);

  if (invalidRequestedPeriod) {
    return (
      <SnapshotErrorPage
        icon={FileText}
        title="舆情报告"
        error={`不支持的报告周期：${requestedPeriod}。请选择 daily、weekly 或 monthly；系统未回退到其他周期。`}
      />
    );
  }

  if (isLoading || base.isLoading) return <SnapshotLoadingPage icon={FileText} title="舆情报告" />;
  if (error || !data || base.error || !base.data) {
    return <SnapshotErrorPage icon={FileText} title="舆情报告" error={error ?? base.error ?? '未知错误'} />;
  }

  const isV3Snapshot = isV3ReportsSnapshot(data);
  const selectedHistoricalReport = isV3Snapshot
    && requestedPeriodId
    && historicalReport?.grain === period
    && historicalReport.period.period_id === requestedPeriodId
    ? historicalReport
    : null;
  const report = selectedHistoricalReport ?? data.current[period];
  const historicalSelectionReady = !isV3Snapshot
    || !requestedPeriodId
    || selectedHistoricalReport !== null;
  const canExport = historicalSelectionReady && !isHistoricalLoading && !historicalError;
  let displayName: string;
  let periodRange: string;
  let coverageSubtitle: string;
  let governanceContract;
  if (isV3Snapshot) {
    const selectedV3Report = selectedHistoricalReport ?? data.current[period];
    displayName = `Momcozy Reddit VOC ${tabConfig[period].label}`;
    periodRange = v3PeriodRange(selectedV3Report);
    coverageSubtitle = selectedV3Report.comparison_contract_proven
      ? `数据所有者确认完整性 ${selectedV3Report.completeness_percent}%`
      : '日历周期已闭合 · 历史采集覆盖未证明';
    governanceContract = createV3ReportGovernanceContract(
      data.release,
      data.manifest,
      data.index,
      selectedV3Report,
    );
  } else {
    const legacyDescriptor = data.index.current[period];
    displayName = legacyDescriptor.display_name;
    periodRange = `${formatDateTime(legacyDescriptor.start_utc)} 至 ${formatDateTime(legacyDescriptor.end_utc)}`;
    coverageSubtitle = legacyDescriptor.coverage_status;
    governanceContract = createReportGovernanceContract(data.release, data.manifest, legacyDescriptor);
  }
  const exportSections = buildExportSections(report);
  const reconciliationAttributes = isV3Report(report)
    ? crossPageReconciliationAttributes({
      page: 'reports',
      sourceSnapshotId: report.source.source_snapshot_id,
      scope: 'momcozy',
      vocType: 'post_voc+comment_context_voc',
      startDate: report.period.start,
      endDate: report.period.end,
      endBoundary: 'exclusive',
    })
    : crossPageReconciliationAttributes({
      page: 'reports',
      sourceSnapshotId: base.data.manifest.source_snapshot_id ?? data.manifest.dataset_version,
      scope: 'momcozy',
      vocType: 'post_voc+comment_context_voc',
      startDate: report.window.start_local.slice(0, 10),
      endDate: report.window.end_local.slice(0, 10),
      endBoundary: 'exclusive',
    });
  const reportFreshness = isV3Snapshot
    ? createBaseDataFreshness(base.data, {
      projectionAsOfLabel: '周期结束（不含）',
      projectionAsOf: data.index.as_of_date,
      projectionAsOfBasis: data.index.comparison_contract_proven
        ? '来自报告 index.as_of_date；覆盖窗口与数据所有者声明在证据详情中单列'
        : '来自报告 index.as_of_date；日历周期闭合，但历史采集覆盖未获数据所有者完整性证明',
      projectionDatasetVersion: data.manifest.dataset_version,
      projectionGeneratedAtUtc: null,
      completenessPercent: data.index.completeness_percent,
      completenessBasis: data.index.coverage_attestation?.attestation_basis ?? 'not_owner_attested',
      evidenceClass: data.index.coverage_attestation?.evidence_class ?? null,
      coverageWindowStart: data.index.coverage_attestation?.coverage_window.start_calendar_date_inclusive ?? null,
      coverageWindowEnd: data.index.coverage_attestation?.coverage_window.end_calendar_date_inclusive ?? null,
    })
    : createBaseDataFreshness(base.data, {
      projectionAsOfLabel: '报告生成锚点',
      projectionAsOf: data.manifest.generated_at_utc,
      projectionAsOfBasis: '旧版报告 manifest 生成时间；不等同于采集任务完成时间',
      projectionDatasetVersion: data.manifest.dataset_version,
      projectionGeneratedAtUtc: data.manifest.generated_at_utc,
    });
  const exportRows = isV3Report(report)
    ? report.indicators.filter(isDisplayableReportIndicator).map((indicator) => ({
      指标ID: indicator.metric_id,
      指标: indicator.name_cn,
      当前值: indicator.current.display,
      环比: indicator.comparisons.period_over_period.status === 'unavailable' ? '' : indicator.comparisons.period_over_period.display,
      同比: indicator.comparisons.year_over_year.status === 'unavailable' ? '' : indicator.comparisons.year_over_year.display,
      趋势: indicator.sparkline.status === 'unavailable' ? '' : indicator.sparkline.direction ?? '',
    }))
    : isRiskReport(report)
    ? report.risk_themes.flatMap((theme) => theme.evidence_refs.map((evidence) => ({
      风险主题: theme.risk_theme_id,
      优先级: theme.effective_priority,
      实体类型: evidence.entity_type,
      证据ID: evidence.entity_id,
      帖子ID: evidence.post_id,
    })))
    : report.evidence_posts.map((post) => ({
      标题: post.title,
      社区: post.subreddit,
      主题: formatTopic(post.topic),
      情感: SENTIMENT_LABELS[post.sentiment],
      时间: post.created_at_utc,
      Reddit链接: post.permalink,
    }));

  if (captureMode) {
    const posterHeights: Record<ReportPeriod, number> = {
      daily: 1800,
      weekly: 2000,
      monthly: 2200,
    };
    const selectedV3Report = isV3Report(report) ? report : null;
    const captureDataAsOf = isV3ReportsSnapshot(data)
      ? data.index.as_of_date
      : data.manifest.generated_at_utc;
    const captureReady = Boolean(
      isV3Snapshot
      && selectedV3Report
      && historicalSelectionReady
      && !isHistoricalLoading
      && !historicalError,
    );
    const captureError = historicalError
      ?? (!isV3Snapshot || !selectedV3Report ? '海报截图只支持已校验的 V3 报告。' : null);

    return (
      <SnapshotPageLayout
        icon={FileText}
        title="舆情报告"
        description="Momcozy 真实日报、周报、月报"
        captureMode
      >
        <section
          data-report-capture-root="poster"
          data-report-ready={captureReady ? 'true' : 'false'}
          data-report-period={period}
          data-report-period-id={selectedV3Report?.period.period_id ?? ''}
          data-report-release-id={data.release.release_id}
          data-report-dataset-version={data.manifest.dataset_version}
          data-report-coverage={selectedV3Report?.completeness_percent ?? ''}
          data-report-data-as-of={captureDataAsOf}
          data-report-source-freshness={base.data.release.freshness?.status ?? 'missing'}
          data-report-capture-width="1440"
          data-report-capture-height={posterHeights[period]}
          className="relative box-border w-[1440px] overflow-hidden bg-surface-secondary px-12 py-10"
          style={{ height: `${posterHeights[period]}px` }}
          aria-label={`${tabConfig[period].label}截图海报`}
        >
          <header className="rounded-card border border-border-divider bg-white px-7 py-6 shadow-sm" data-report-capture-identity>
            <div className="flex items-start justify-between gap-8">
              <div>
                <p className="text-tiny font-semibold uppercase tracking-[0.18em] text-primary">Momcozy · Reddit VOC</p>
                <h1 className="mt-2 text-display font-semibold text-foreground">{displayName}</h1>
                <p className="mt-2 text-body text-foreground-secondary">{periodRange} · Asia/Shanghai · {selectedV3Report?.comparison_contract_proven ? '完整闭合周期' : '日历周期已闭合，覆盖未证明'}</p>
              </div>
              <div className="rounded-card bg-primary-light px-5 py-4 text-right">
                <p className="text-tiny font-semibold text-primary">数据完整性</p>
                <p className="mt-1 text-h1 font-semibold text-foreground">{selectedV3Report?.comparison_contract_proven ? `${selectedV3Report.completeness_percent}%` : '未证明'}</p>
              </div>
            </div>
            <dl className="mt-5 grid grid-cols-4 gap-3 border-t border-border-divider pt-4 text-tiny">
              <div><dt className="text-foreground-muted">周期 ID</dt><dd className="mt-1 truncate font-mono text-foreground-secondary">{selectedV3Report?.period.period_id ?? '—'}</dd></div>
              <div><dt className="text-foreground-muted">数据截止</dt><dd className="mt-1 font-medium text-foreground-secondary">{captureDataAsOf}</dd></div>
              <div><dt className="text-foreground-muted">数据版本</dt><dd className="mt-1 truncate font-mono text-foreground-secondary">{data.manifest.dataset_version}</dd></div>
              <div><dt className="text-foreground-muted">发布版本</dt><dd className="mt-1 truncate font-mono text-foreground-secondary">{data.release.release_id}</dd></div>
            </dl>
          </header>

          {captureError ? (
            <div className="mt-6 rounded-card border border-status-error/30 bg-status-errorBg p-6 text-status-error" role="alert" data-report-capture-error>
              {captureError}
            </div>
          ) : null}
          {captureReady && selectedV3Report ? (
            <div className="mt-6">
              <RealReportView report={selectedV3Report} snapshot={base.data} posterMode />
            </div>
          ) : null}

          <footer className="absolute bottom-7 left-12 right-12 flex items-center justify-between border-t border-border-divider pt-3 text-tiny text-foreground-muted">
            <span>帖子与评论共同进入治理后的 VOC 指标；帖子保持独立分析。</span>
            <span>内部经营分析 · 自动生成 · 禁止脱离指标口径单独传播</span>
          </footer>
        </section>
      </SnapshotPageLayout>
    );
  }

  return (
    <SnapshotPageLayout
      icon={FileText}
      title="舆情报告"
      description="Momcozy 真实日报、周报、月报 · 从经营判断到行动建议"
      datasetVersion={data.manifest.dataset_version}
      freshness={reportFreshness}
    >
      <div className="flex flex-col gap-4" {...reconciliationAttributes}>
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <Calendar className="h-5 w-5 text-primary" strokeWidth={1.5} />
              <h2 className="text-h1 text-foreground">{displayName}</h2>
            </div>
            <p className="mt-1 text-body text-foreground-secondary">
              {periodRange} · Asia/Shanghai
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => void reload()}
              disabled={isReloading}
              className="inline-flex items-center gap-1.5 rounded-button border border-border-divider px-3 py-2 text-body-sm font-medium text-foreground-secondary transition-colors hover:bg-surface-tertiary disabled:cursor-not-allowed disabled:opacity-60"
              title="重新读取并校验当前发布指针；不会触发数据采集"
            >
              <RefreshCw className={`h-4 w-4 text-primary ${isReloading ? 'animate-spin' : ''}`} strokeWidth={1.5} />
              {isReloading ? '重新读取中' : '重新读取当前发布版本'}
            </button>
            {canExport ? (
              <ExportButton
                size="md"
                data={exportRows}
                sections={exportSections}
                title={`Reddit VOC ${tabConfig[period].label}`}
                subtitle={`${displayName} · ${coverageSubtitle}`}
                filename={`Reddit_VOC_${selectedHistoricalReport ? selectedHistoricalReport.period.period_id.replaceAll(':', '_') : `latest_complete_${period}`}_${data.manifest.dataset_version}`}
              />
            ) : (
              <button
                type="button"
                disabled
                className="inline-flex min-h-11 items-center rounded-button border border-border-divider bg-surface-tertiary px-3 text-body-sm font-medium text-foreground-muted opacity-60"
              >
                报告校验后可导出
              </button>
            )}
          </div>
        </div>

        <div className="flex flex-col gap-2 rounded-xl border border-border-divider/60 bg-white px-4 py-3 shadow-sm sm:flex-row sm:items-center sm:justify-between" role="region" aria-label="报告可用周期">
          <div>
            <p className="text-tiny font-semibold uppercase tracking-[0.12em] text-foreground-muted">报告周期</p>
            <p className="mt-0.5 text-body-sm font-medium text-foreground">{currentPeriodLabel(period, report)}</p>
            {isV3Snapshot && data.historyIndex ? (
              <p className="mt-1 text-tiny text-foreground-muted" data-archive-visibility="internal-comparison-only">
                {data.index.comparison_contract_proven
                  ? '环比与同比基期内置；内部比较归档不作为业务入口。'
                  : data.historyIndex.reports[period].length > 0
                    ? '历史已观测周期可选择；同环比与六期趋势按观测口径展示，全量采集完整性与正式趋势结论仍保持关闭。'
                    : '历史采集覆盖未获完整性证明；当前版本尚未发布历史已观测周期。'}
              </p>
            ) : null}
          </div>
          <div className="flex flex-col items-start gap-1 sm:items-end">
            {isV3Snapshot && data.historyIndex ? (
              <label className="flex items-center gap-2 text-caption text-foreground-muted">
                <span>选择闭合周期</span>
                <select
                  aria-label="选择历史报告周期"
                  value={requestedPeriodId ?? 'current'}
                  onChange={(event) => {
                    const next = new URLSearchParams(searchParams);
                    const value = event.target.value;
                    if (value === 'current') next.delete('period_id');
                    else next.set('period_id', value);
                    setSearchParams(next, { replace: false });
                  }}
                  className="min-h-11 rounded-lg border border-border-divider bg-white px-3 text-body-sm text-foreground focus:border-primary focus:outline-none"
                >
                  <option value="current">{data.index.comparison_contract_proven ? '最新完整周期' : '最新闭合周期（覆盖未证明）'}</option>
                  {data.historyIndex.reports[period].map((entry) => (
                    <option key={entry.period.period_id} value={entry.period.period_id}>
                      {historyPeriodLabel(period, entry)}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            <p className="text-caption text-foreground-muted">
              {isV3Snapshot ? '周期结束（不含）' : '数据锚点'}：{isV3Snapshot ? data.index.as_of_date : formatDateTime(data.manifest.generated_at_utc)}
            </p>
          </div>
        </div>

        {isHistoricalLoading ? (
          <p className="rounded-xl border border-border-divider/60 bg-white px-4 py-3 text-body-sm text-foreground-muted" role="status">
            正在校验并加载所选历史报告…
          </p>
        ) : null}
        {historicalError ? (
          <p className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-body-sm text-amber-900" role="alert">
            {historicalError}
          </p>
        ) : null}

        <div className="flex items-center gap-2 rounded-xl border border-border-divider/60 bg-white p-2 shadow-sm" aria-label="报告周期">
          {(Object.keys(tabConfig) as ReportPeriod[]).map((tab) => (
            <button
              key={tab}
              type="button"
              onClick={() => setPeriod(tab)}
              aria-pressed={period === tab}
              className={`flex flex-1 flex-col items-center rounded-lg px-2 py-3 transition-all duration-200 sm:px-4 ${
                period === tab
                  ? 'bg-primary text-white shadow-md shadow-primary/20'
                  : 'text-foreground-muted hover:bg-surface-tertiary hover:text-foreground'
              }`}
            >
              <span className={`text-body-sm font-semibold ${period === tab ? 'text-white' : 'text-foreground'}`}>{tabConfig[tab].label}</span>
              <span className={`mt-0.5 hidden text-tiny sm:block ${period === tab ? 'text-white/80' : 'text-foreground-muted/70'}`}>
                {tabConfig[tab].description}
              </span>
            </button>
          ))}
        </div>

        <DataScopeBar contract={governanceContract} />
        <p className="text-tiny leading-relaxed text-foreground-muted">
          {CROSS_PAGE_RECONCILIATION_RULE_CN}
        </p>
      </div>

      {!isHistoricalLoading && !historicalError ? (
        <RealReportView report={report} snapshot={base.data} />
      ) : null}
    </SnapshotPageLayout>
  );
}
