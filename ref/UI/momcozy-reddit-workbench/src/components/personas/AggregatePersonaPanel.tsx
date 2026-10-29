import { AlertTriangle, CircleHelp, CircleUserRound, LoaderCircle, ShieldCheck } from 'lucide-react';
import { buildSnapshotEvidenceHref } from '../../features/redditSnapshot/evidenceLinks';
import {
  V3_PERSONAS_MANIFEST_SCHEMA,
  buildV3PersonaEvidenceHref,
} from '../../features/redditSnapshot/personas';
import type {
  RedditPersonasSnapshot,
  V3RedditPersonasSnapshot,
} from '../../features/redditSnapshot/personas';
import AggregatePersonaCard from './AggregatePersonaCard';
import type { AggregatePersonaCardModel } from './AggregatePersonaCard';

export type AnyRedditPersonasSnapshot = RedditPersonasSnapshot | V3RedditPersonasSnapshot;

interface AggregatePersonaPanelProps {
  data: AnyRedditPersonasSnapshot | null;
  error: string | null;
  isLoading: boolean;
  assignmentIds?: ReadonlySet<string> | readonly string[];
  periodLabel?: string;
  categoryContextAssignmentCount?: number;
  categoryContextUniqueEntityCount?: number;
  /** Authoritative per-cohort counts from the daily-recomputed quarter projection.
   *  The persona snapshot cannot be rebuilt by the pipeline, so its assignment ids
   *  and the quarter's live ids are disjoint in production; the distribution must
   *  read the quarter counts or every cohort renders 0.00%. */
  cohortAssignmentCounts?: Readonly<Record<string, number>>;
  /** `quarterInsights.personas.main_assignment_count` — the denominator the panel
   *  must reconcile against before it may print a 100.00% total. */
  declaredMainAssignmentCount?: number;
}

function isV3Snapshot(data: AnyRedditPersonasSnapshot): data is V3RedditPersonasSnapshot {
  return data.manifest.schema_version === V3_PERSONAS_MANIFEST_SCHEMA;
}

/** The persona cohort cards come from a versioned snapshot that the daily pipeline
 * cannot rebuild (it needs the out-of-repo governed-signal and persona-dictionary
 * engines). Counts above them are current-quarter values, so when the snapshot
 * predates the quarter the caption has to say so rather than imply freshness. */
export function personaSnapshotDate(data: AnyRedditPersonasSnapshot): string | null {
  const generated = data.manifest.generated_at_utc;
  return typeof generated === 'string' && /^\d{4}-\d{2}-\d{2}/.test(generated)
    ? generated.slice(0, 10)
    : null;
}

export function quarterStartDate(periodLabel?: string): string | null {
  const match = periodLabel?.match(/(\d{4}-\d{2}-\d{2})/);
  return match ? match[1] : null;
}

function availabilityLabel(status: string): string {
  if (status === 'stable_observed_sample') return '稳定观察样本';
  if (status === 'directional_observed_sample') return '方向性观察样本';
  if (status === 'unavailable_insufficient_observed_sample') return '观察证据不足';
  return '已发布观察样本';
}

function businessPersonaDefinition(definition: string): string {
  return definition
    .replaceAll('同一 VOC', '同一条内容')
    .replace(/已晋级显式推荐标签\s+[A-Z0-9-]+/g, '明确推荐表达')
    .replaceAll('画像桥接证据', '画像关联证据')
    .replaceAll('受治理竞品实体证据', '明确竞品提及')
    .replaceAll('受治理操作痛点', '明确操作痛点')
    .replaceAll('画像原子', '画像依据');
}

function allocateDisplayShares(counts: number[]): number[] {
  const total = counts.reduce((sum, count) => sum + count, 0);
  if (total <= 0) return counts.map(() => 0);
  const scaled = counts.map((count) => (count * 10000) / total);
  const hundredths = scaled.map(Math.floor);
  const remainder = 10000 - hundredths.reduce((sum, value) => sum + value, 0);
  const order = scaled
    .map((value, index) => ({ index, fraction: value - Math.floor(value) }))
    .sort((left, right) => right.fraction - left.fraction || left.index - right.index);
  for (let index = 0; index < remainder; index += 1) {
    hundredths[order[index % order.length].index] += 1;
  }
  return hundredths.map((value) => value / 100);
}

function PersonaDistributionChart({
  cohorts,
  totalAssignments,
  categoryContextAssignments,
  categoryContextUniqueEntities,
  momcozyScoped,
  periodLabel,
  denominatorNote,
}: {
  cohorts: AggregatePersonaCardModel[];
  totalAssignments: number;
  categoryContextAssignments: number;
  categoryContextUniqueEntities?: number;
  momcozyScoped: boolean;
  periodLabel?: string;
  /** Non-null when the displayed sum does not exhaust the declared denominator.
   *  In that case the 100.00% badge is a false claim and must be replaced. */
  denominatorNote?: string | null;
}) {
  const title = momcozyScoped
    ? `${periodLabel ? `${periodLabel} · ` : ''}Momcozy 相关内容画像赋值占比`
    : '不同用户画像分组占比';
  return (
    <div
      className="mb-5 rounded-[24px] border border-border-divider bg-white p-5 shadow-card sm:p-6"
      data-testid="persona-distribution-chart"
      aria-labelledby="persona-distribution-title"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h3 id="persona-distribution-title" className="text-h3 text-foreground">{title}</h3>
            <button
              type="button"
              aria-label={`${title}口径说明`}
              title={momcozyScoped
                ? `占比等于本组 Momcozy 相关内容画像赋值次数除以全部 Momcozy 画像赋值次数；仅纳入 Momcozy 直接相关内容及含 Momcozy 的多品牌对比内容。另有 ${categoryContextAssignments.toLocaleString('zh-CN')} 次母婴品类语境赋值仅作背景，不进入主占比。同一内容可进入多个画像组，因此不是用户人数或人口占比。`
                : '占比等于本组画像归属数除以全部画像归属数；同一条帖子或评论可进入多个画像组，因此不是独立用户人口占比。'}
              className="text-foreground-muted transition-colors hover:text-foreground"
            >
              <CircleHelp className="h-4 w-4" strokeWidth={1.5} aria-hidden="true" />
            </button>
          </div>
          <p className="mt-1 max-w-4xl text-caption leading-relaxed text-foreground-secondary">
            {momcozyScoped ? (
              `占比 = 本组 Momcozy 相关内容画像赋值次数 / ${totalAssignments.toLocaleString('zh-CN')} 次 Momcozy 画像赋值；仅纳入 Momcozy 直接相关内容及含 Momcozy 的多品牌对比内容。另有 ${categoryContextAssignments.toLocaleString('zh-CN')} 次母婴品类语境赋值${categoryContextUniqueEntities === undefined ? '' : `（覆盖 ${categoryContextUniqueEntities.toLocaleString('zh-CN')} 个内容实体）`}仅作背景，不进入主占比；同一内容可进入多个画像组，非用户人数或人口占比。`
            ) : (
              <>占比 = 本组画像归属数 / {totalAssignments.toLocaleString('zh-CN')} 条全部画像归属数；同一内容可进入多个画像组，非独立用户人口占比。</>
            )}
          </p>
        </div>
        {denominatorNote ? (
          <span
            className="rounded-badge border border-status-warning/30 bg-status-warningBg px-3 py-1.5 text-tiny font-medium text-foreground-secondary"
            data-testid="persona-denominator-note"
          >
            {denominatorNote}
          </span>
        ) : (
          <span className="rounded-badge bg-primary-light px-3 py-1.5 text-tiny font-semibold text-primary-hover">合计 100.00%</span>
        )}
      </div>

      <div className="mt-5 grid gap-x-8 gap-y-4 lg:grid-cols-2" role="list" aria-label={momcozyScoped ? '各类 Momcozy 相关内容画像赋值占比' : '各类用户画像证据占比'}>
        {cohorts.map((cohort) => (
          <div
            key={cohort.cohortId}
            role="listitem"
            data-testid="persona-distribution-bar"
            data-share={cohort.distributionShare.toFixed(2)}
          >
            <div className="mb-1.5 flex items-center justify-between gap-3 text-caption">
              <span className="font-medium text-foreground">{cohort.name}</span>
              <span className="shrink-0 tabular-nums text-foreground-secondary">
                {cohort.distributionShare.toFixed(2)}% · {cohort.assignmentCount.toLocaleString('zh-CN')} 条
              </span>
            </div>
            <div
              className="h-2.5 overflow-hidden rounded-full bg-surface-tertiary"
              role="progressbar"
              aria-label={`${cohort.name}${momcozyScoped ? 'Momcozy 相关内容画像赋值占比' : '画像证据占比'}`}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={cohort.distributionShare}
            >
              <div
                className="h-full rounded-full bg-gradient-to-r from-primary to-[#27A67A]"
                style={{ width: `${cohort.distributionShare}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function AggregatePersonaPanel({
  data,
  error,
  isLoading,
  assignmentIds,
  periodLabel,
  categoryContextAssignmentCount,
  categoryContextUniqueEntityCount,
  cohortAssignmentCounts,
  declaredMainAssignmentCount,
}: AggregatePersonaPanelProps) {
  if (isLoading) {
    return (
      <section
        className="card flex min-h-56 items-center justify-center p-8 text-center"
        aria-label="正在加载用户画像"
        aria-busy="true"
        aria-live="polite"
      >
        <div>
          <LoaderCircle className="mx-auto h-7 w-7 text-primary motion-safe:animate-spin" strokeWidth={1.5} aria-hidden="true" />
          <p className="mt-3 text-body-sm font-medium text-foreground">加载用户画像</p>
          <p className="mt-1 text-caption text-foreground-secondary">正在校验画像 JSON 与本地合成头像</p>
        </div>
      </section>
    );
  }

  if (error || !data) {
    return (
      <section className="card border border-status-error/20 p-5 sm:p-6" aria-labelledby="persona-error-title" aria-live="polite" data-ui-severity="error">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-icon bg-status-errorBg">
            <AlertTriangle className="h-5 w-5 text-status-error" strokeWidth={1.5} aria-hidden="true" />
          </div>
          <div>
            <h2 id="persona-error-title" className="text-h3 text-foreground">真实用户画像不可用，未回退 Mock</h2>
            <p className="mt-2 break-words text-body-sm text-foreground-secondary">{error ?? '画像数据不可用'}</p>
            <p className="mt-2 text-caption text-foreground-secondary">
              既有语义洞察仍可查看；本模块不会用演示画像数据补位。
            </p>
          </div>
        </div>
      </section>
    );
  }

  const v3 = isV3Snapshot(data);
  let cardModels: AggregatePersonaCardModel[];
  let categoryContextAssignments = 0;
  if (v3) {
    const assignmentIdSet = assignmentIds ? new Set(assignmentIds) : null;
    const scopedAssignments = assignmentIdSet
      ? data.tags.assignments.filter((assignment) => assignmentIdSet.has(assignment.assignment_id))
      : data.tags.assignments;
    const momcozyAssignments = scopedAssignments.filter((assignment) => (
      assignment.scope === 'momcozy_direct' || assignment.scope === 'momcozy_multi'
    ));
    categoryContextAssignments = categoryContextAssignmentCount
      ?? scopedAssignments.filter((assignment) => assignment.scope === 'category_context').length;
    const evidenceByCohort = new Map<string, V3RedditPersonasSnapshot['tags']['assignments'][number]>();
    const scopeRank = { momcozy_direct: 0, momcozy_multi: 1, category_context: 2 } as const;
    const gradeRank = { promoted_tag_evidence: 0, governed_rule_observation: 1 } as const;
    const evidenceRows = [...momcozyAssignments].sort((left, right) => (
      scopeRank[left.scope] - scopeRank[right.scope]
      || gradeRank[left.evidence_grade] - gradeRank[right.evidence_grade]
      || Number(right.source_entity_type === 'post') - Number(left.source_entity_type === 'post')
      || left.assignment_id.localeCompare(right.assignment_id)
    ));
    for (const assignment of evidenceRows) {
      if (!evidenceByCohort.has(assignment.cohort_id)) evidenceByCohort.set(assignment.cohort_id, assignment);
    }
    const bridgeByCohort = new Map(data.bridge.cohorts.map((cohort) => [cohort.cohort_id, cohort]));
    const personaNameById = new Map(data.catalog.atomic_personas.map((persona) => [persona.persona_id, persona.persona_name]));
    cardModels = data.data.personas.map((cohort) => {
      const assignment = evidenceByCohort.get(cohort.cohort_id);
      const cohortAssignments = momcozyAssignments.filter((row) => row.cohort_id === cohort.cohort_id);
      // The quarter projection is the live, daily-recomputed truth. The persona
      // snapshot is a frozen artifact whose assignment ids are a different
      // namespace, so filtering by them yields zero in production. Prefer the
      // quarter count whenever it is published; only fall back to the local
      // filter when no quarterly block exists (July fixtures, offline snapshots).
      const quarterCount = cohortAssignmentCounts?.[cohort.cohort_id];
      const assignmentCount = typeof quarterCount === 'number'
        ? quarterCount
        : cohortAssignments.length;
      // The entity split can only be attributed when the local assignment rows
      // actually reconcile with the count being displayed. Otherwise it is
      // unknown, not zero.
      const splitIsAttributable = cohortAssignments.length === assignmentCount;
      return {
        cohortId: cohort.cohort_id,
        name: cohort.name_cn,
        definition: businessPersonaDefinition(cohort.definition),
        statusLabel: periodLabel
          ? availabilityLabel(assignmentCount >= 30
              ? 'stable_observed_sample'
              : assignmentCount >= 10
                ? 'directional_observed_sample'
                : 'unavailable_insufficient_observed_sample')
          : availabilityLabel(cohort.status),
        avatarAlt: cohort.avatar.alt_text,
        assignmentCount,
        distributionShare: 0,
        postCount: splitIsAttributable
          ? cohortAssignments.filter((row) => row.source_entity_type === 'post').length
          : null,
        commentCount: splitIsAttributable
          ? cohortAssignments.filter((row) => row.source_entity_type === 'comment').length
          : null,
        threadCount: splitIsAttributable
          ? new Set(cohortAssignments.map((row) => row.thread_id)).size
          : null,
        atomicReferenceCount: cohort.persona_atomic_tag_count,
        referenceTags: (bridgeByCohort.get(cohort.cohort_id)?.persona_tag_ids ?? [])
          .map((personaId) => personaNameById.get(personaId))
          .filter((name): name is string => Boolean(name))
          .slice(0, 4),
        evidenceHref: assignment
          ? buildV3PersonaEvidenceHref(assignment, data.manifest.snapshot_id, data.releaseId)
          : null,
        momcozyScoped: true,
      };
    });
  } else {
    const firstEvidencePostByPersona = new Map<string, string>();
    for (const assignment of data.tags.assignments) {
      if (!firstEvidencePostByPersona.has(assignment.persona_id)) {
        firstEvidencePostByPersona.set(assignment.persona_id, assignment.post_id);
      }
    }
    cardModels = data.data.personas.map((persona) => ({
      cohortId: persona.persona_id,
      name: persona.name_cn,
      definition: persona.definition,
      statusLabel: availabilityLabel(persona.status),
      avatarAlt: persona.avatar.alt_text,
      assignmentCount: persona.metrics.matched_entities,
      distributionShare: 0,
      postCount: persona.metrics.matched_posts,
      commentCount: persona.metrics.matched_comments,
      threadCount: persona.metrics.threads,
      atomicReferenceCount: null,
      referenceTags: [
        ...persona.dictionary_reference.story_lines,
        ...persona.dictionary_reference.intent_type,
        ...persona.dictionary_reference.problem_type,
      ].slice(0, 4),
      evidenceHref: firstEvidencePostByPersona.get(persona.persona_id)
        ? buildSnapshotEvidenceHref({
            postId: firstEvidencePostByPersona.get(persona.persona_id) ?? '',
            releaseId: data.releaseId,
            snapshotId: data.manifest.dataset_version,
            source: 'personas',
          })
        : null,
      momcozyScoped: false,
    }));
  }

  const cohortCount = v3 ? data.data.persona_cohort_count : data.data.persona_count;
  const displayShares = allocateDisplayShares(cardModels.map((cohort) => cohort.assignmentCount));
  cardModels = cardModels
    .map((cohort, index) => ({ ...cohort, distributionShare: displayShares[index] }))
    .sort((left, right) => right.assignmentCount - left.assignmentCount || left.name.localeCompare(right.name, 'zh-CN'));
  const totalAssignments = cardModels.reduce((sum, cohort) => sum + cohort.assignmentCount, 0);
  // The 100.00% total is a claim that the displayed rows exhaust the denominator.
  // Print it only when that is arithmetically true; otherwise say the denominator
  // is unavailable and show both numbers, so a partial count never reads as whole.
  const declaredTotal = typeof declaredMainAssignmentCount === 'number'
    ? declaredMainAssignmentCount
    : null;
  const totalIsSelfEvident = totalAssignments > 0
    && (declaredTotal === null || declaredTotal === totalAssignments);
  const denominatorNote = totalIsSelfEvident
    ? null
    : declaredTotal === null
      ? `分母不可用（已展示 ${totalAssignments.toLocaleString('zh-CN')} 条，季度总数未提供）`
      : `分母不可用（已展示 ${totalAssignments.toLocaleString('zh-CN')} / 声明 ${declaredTotal.toLocaleString('zh-CN')}）`;
  const snapshotDate = personaSnapshotDate(data);
  const quarterStart = quarterStartDate(periodLabel);
  const staleSnapshotNote = snapshotDate && quarterStart && snapshotDate < quarterStart
    ? `画像分组快照生成于 ${snapshotDate}，早于当前统计季度起点 ${quarterStart}；分组卡片来自该快照，上方计数为当前季度实时值。`
    : null;

  return (
    <section aria-labelledby="aggregate-personas-title">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <CircleUserRound className="h-5 w-5 text-primary-hover" strokeWidth={1.5} aria-hidden="true" />
            <h2 id="aggregate-personas-title" className="text-h2 text-foreground">用户画像</h2>
          </div>
          <p className="mt-1 max-w-3xl text-caption leading-relaxed text-foreground-secondary">
            {v3
              ? `${periodLabel ? `${periodLabel}内，` : ''}从 Momcozy 相关真实 Reddit 帖子与评论中的需求、问题和使用场景归纳画像分组；每类画像均可回到原始证据核查。画像是内容证据分组，不是真实用户身份或人数。`
              : '从真实 Reddit 帖子与评论中的需求、问题和使用场景归纳画像分组；每类画像均可回到原始证据核查。'}
          </p>
          {staleSnapshotNote ? (
            <p
              className="mt-1 max-w-3xl text-caption leading-relaxed text-foreground-muted"
              data-testid="persona-snapshot-note"
            >
              {staleSnapshotNote}
            </p>
          ) : null}
        </div>
        <div className="inline-flex max-w-full items-center gap-2 rounded-badge border border-primary/20 bg-primary-light px-3 py-1.5 text-tiny font-medium text-foreground-secondary">
          <ShieldCheck className="h-3.5 w-3.5 text-primary-hover" strokeWidth={1.5} aria-hidden="true" />
          <span className="truncate">
            {cohortCount} 类用户画像
            {' · '}真实帖子与评论证据
          </span>
        </div>
      </div>

      <PersonaDistributionChart
        cohorts={cardModels}
        totalAssignments={totalAssignments}
        categoryContextAssignments={categoryContextAssignments}
        categoryContextUniqueEntities={categoryContextUniqueEntityCount}
        momcozyScoped={v3}
        periodLabel={periodLabel}
        denominatorNote={denominatorNote}
      />

      <div className={`grid gap-4 md:grid-cols-2 ${cohortCount > 2 ? 'xl:grid-cols-3' : ''}`}>
        {cardModels.map((cohort) => (
          <AggregatePersonaCard
            key={cohort.cohortId}
            cohort={cohort}
            avatarAsset={data.avatarAssets[cohort.cohortId as keyof typeof data.avatarAssets] ?? { url: null, error: '头像运行态缺失' }}
          />
        ))}
      </div>
    </section>
  );
}
