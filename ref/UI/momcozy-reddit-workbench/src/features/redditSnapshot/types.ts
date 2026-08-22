import type { CurrentRelease } from './release';

export type SnapshotSentiment = 'positive' | 'neutral' | 'negative';
export type SnapshotManifestSchema =
  | 'reddit_voc_site_snapshot_manifest_v1'
  | 'reddit_voc_site_snapshot_manifest_v2'
  | 'reddit_voc_site_snapshot_manifest_v3';
export type SnapshotCoverageGrade = 'full' | 'partial' | 'post_only' | 'source_observed';
export type SnapshotCommentCoverageStatus =
  | 'thread_complete'
  | 'observed_first_page'
  | 'post_only'
  | 'source_rows_only';

export interface SnapshotProductCategory {
  id: string;
  name_en: string;
  name_cn: string;
}

export interface SnapshotProductFamily {
  id: string;
  name_en: string;
  name_cn: string;
}

export interface SnapshotProductSpu {
  spu_id: string;
  spu_name: string;
}

export interface SnapshotProductBinding {
  brand_id: 'momcozy';
  category: SnapshotProductCategory;
  product_family: SnapshotProductFamily | null;
  exact_spu: SnapshotProductSpu | null;
  binding_level: 'category' | 'product_family' | 'spu_exact';
  match_type: 'category_context' | 'contextual_alias' | 'strong_name';
  matched_alias: string;
  governance_status: 'category_only' | 'family_only' | 'exact_spu_approved' | 'taxonomy_blocked';
  governance_reason: string | null;
}

export interface SnapshotProductCoverage {
  input_record_count: number;
  bound_record_count: number;
  unbound_record_count: number;
  multi_binding_record_count: number;
  binding_count: number;
  exact_spu_binding_count: number;
  family_only_binding_count: number;
  category_only_binding_count: number;
  taxonomy_blocked_binding_count: number;
  category_binding_counts: Record<string, number>;
  family_binding_counts: Record<string, number>;
  is_conserved: true;
}

export interface SnapshotProductResolution {
  status: 'resolved';
  resolver_version: 'product-entity-resolver-v1';
  ledger_version: 'momcozy-product-entity-ledger-2026-07-15.v1';
  ledger_sha256: string;
  coverage: {
    posts: SnapshotProductCoverage;
    comments: SnapshotProductCoverage;
    combined: SnapshotProductCoverage;
  };
  observed_tag_contexts: Array<{
    product_line: string;
    voc_category: string;
    spu_ids: string[];
  }>;
}

export interface SnapshotAnalysis {
  analysis_version: string;
  sentiment_label: SnapshotSentiment;
  sentiment_score: number;
  topic: string;
  severity: string;
  confidence: number;
  pain_points: string[];
  provider_call: boolean;
}

export interface SnapshotTagMatch {
  tag_id: string;
  tag_scope: string;
  tag_sentiment: string;
  evidence_keywords: string[];
  evidence_count: number;
  match_strength: string;
  validation_status: string;
}

export interface SnapshotTagging {
  dictionary_version: string;
  tag_ids: string[];
  aspect_tag_ids: string[];
  brand_tag_ids: string[];
  matches: SnapshotTagMatch[];
  semantic_validation_status: string;
}

export type SnapshotTranslationQualityStatus = 'deterministic_passed_unreviewed';

export interface SnapshotPostTranslation {
  title_zh: string;
  content_zh: string;
  title_input_sha256: string;
  content_input_sha256: string;
  title_quality_status: SnapshotTranslationQualityStatus;
  content_quality_status: SnapshotTranslationQualityStatus;
  provider: 'deepseek';
  model: 'deepseek-v4-flash';
  semantic_validation: 'not_run';
  independent_human_review: false;
}

export interface SnapshotCommentTranslation {
  body_zh: string;
  input_sha256: string;
  quality_status: SnapshotTranslationQualityStatus;
  provider: 'deepseek';
  model: 'deepseek-v4-flash';
  semantic_validation: 'not_run';
  independent_human_review: false;
}

export interface SnapshotPost {
  schema_version?: 'reddit_voc_public_post_v3';
  post_id: string;
  reddit_id: string;
  title: string;
  content: string;
  subreddit: string;
  permalink: string;
  permalink_basis?: 'source_permalink' | 'source_url' | 'canonical_reddit_identity';
  created_at_utc: string;
  score: number;
  upvote_ratio: number | null;
  num_comments_reported: number | null;
  linked_comment_count: number;
  structural_coverage_grade: SnapshotCoverageGrade;
  count_completeness_status: string;
  event_created_at_utc?: string | null;
  source_calendar_date?: string | null;
  event_time_precision?: 'instant' | 'day';
  title_basis?: 'source_title' | 'source_summary' | 'content_excerpt' | 'content_unavailable';
  comment_coverage_status?: SnapshotCommentCoverageStatus;
  brand_binding?: ControlledBrandBinding;
  product_bindings?: SnapshotProductBinding[];
  author_pseudonym?: string | null;
  author_pseudonym_status?: 'suppressed_for_public_projection';
  collection_buckets?: string[];
  source_kinds?: string[];
  mentioned_brands: string[];
  analysis: SnapshotAnalysis;
  tagging: SnapshotTagging;
  evidence_id: string;
  pii_redaction_flags?: string[];
  record_authority?: 'governed_base' | 'workbook_net_new';
  translation?: SnapshotPostTranslation;
}

export interface SnapshotComment {
  schema_version?: 'reddit_voc_public_comment_v3';
  comment_id: string;
  reddit_id: string;
  post_id: string;
  parent_id: string | null;
  parent_link_status?: string;
  body: string;
  subreddit?: string;
  permalink?: string;
  permalink_basis?: 'parent_post_permalink' | 'source_url';
  created_at_utc: string;
  score: number;
  depth: number | null;
  deleted_or_removed: boolean;
  is_bot: boolean | null;
  event_created_at_utc?: string | null;
  source_calendar_date?: string | null;
  event_time_precision?: 'instant' | 'day';
  brand_binding?: ControlledBrandBinding;
  mentioned_brands?: string[];
  product_bindings?: SnapshotProductBinding[];
  author_pseudonym?: string | null;
  author_pseudonym_status?: 'suppressed_for_public_projection';
  include_in_voc_metrics: boolean | null;
  metric_eligibility_status?: 'source_explicit' | 'determined_in_governed_metrics_not_base_projection';
  analysis: SnapshotAnalysis;
  tagging: SnapshotTagging;
  evidence_id: string;
  pii_redaction_flags?: string[];
  record_authority?: 'governed_base' | 'workbook_net_new';
  translation?: SnapshotCommentTranslation;
}

export interface SnapshotManifest {
  schema_version: SnapshotManifestSchema;
  dataset_version: string;
  generated_at_utc: string;
  delivery_mode: string;
  all_checks_passed: boolean;
  production_unchanged: boolean;
  provider_call: boolean;
  live_send: boolean;
  database_write?: false;
  remote_write?: false;
  deploy?: false;
  source_snapshot_id?: string;
  status?: 'validated_candidate' | 'validated_local_translation_candidate';
  artifact_stage?: 'privacy_safe_base_public_candidate' | 'local_translation_candidate';
  consumption_status?: 'eligible_for_current_release_candidate_binding' | 'eligible_for_frontend_candidate_consumption';
  promotable?: boolean;
  privacy_safe_projection?: true;
  comparison_contract_basis?: 'owner_attested_dataset_scope_window' | 'not_owner_attested';
  comparison_contract_proven?: boolean;
  comparison_unavailable_reason_codes?: string[];
  completeness_percent?: 100 | null;
  completeness_basis?: 'data_owner_declaration' | 'not_owner_attested';
  coverage_attestation?: {
    attestation_basis: 'data_owner_declaration';
    completeness_percent: 100;
    coverage_window: {
      end_calendar_date_inclusive: string;
      start_calendar_date_inclusive: string;
    };
    evidence_class: 'owner_attested_not_crawler_proof';
    scope: 'canonical_observation_pool';
    source_snapshot_id: string;
  } | null;
  data_owner_coverage_attestation_sha256?: string | null;
  lineage_manifest_sha256?: string;
  inputs?: {
    canonical_dataset_id: string;
    canonical_manifest_sha256: string;
    canonical_validation_receipt_sha256: string;
    tag_dictionary_sha256: string;
  };
  boundaries?: {
    database_write: false;
    deploy: false;
    live_send: false;
    production_unchanged: true;
    provider_call: boolean;
    remote_write: false;
  };
  translations?: {
    schema_version: 'reddit_voc_translation_extension_v1';
    provider: 'deepseek';
    model: 'deepseek-v4-flash';
    provider_call: true;
    provider_authorization_id: string;
    source_dataset_version: string;
    source_public_manifest_sha256: string;
    translation_prompt_sha256: string;
    translation_terms_sha256: string;
    checkpoint_sha256: string;
    provider_attempt_log_sha256: string;
    quality_gate: 'deterministic_contract_v1';
    semantic_validation: 'not_run';
    independent_human_review: false;
    coverage: {
      posts: number;
      post_titles: number;
      post_contents: number;
      comments: number;
      comments_total?: number;
      comments_status?: 'complete' | 'partial';
      comments_unavailable_reason?: null | 'provider_http_402_balance_blocked';
      post_translation_status?: 'complete';
      translated_items: number;
    };
    provider_attempts: number;
    usage: {
      prompt_tokens: number;
      completion_tokens: number;
      prompt_cache_hit_tokens: number;
      prompt_cache_miss_tokens: number;
      total_tokens: number;
    };
  };
  files: Record<string, { bytes: number; sha256: string }>;
  canonical_counts: {
    posts: number;
    linked_comments: number;
    stored_comments: number;
    quarantined_comments: number;
    comments_jsonl?: number;
    unresolved_parent_comments?: number;
  };
  projection_counts?: {
    public_posts: number;
    public_linked_comments: number;
    ledger_only_unresolved_parent_comments: number;
    ledger_only_quarantined_comments: number;
  };
  time_precision?: {
    posts: Partial<Record<'instant' | 'day', number>>;
    comments: Partial<Record<'instant' | 'day', number>>;
    day_precision_midnight_imputed: false;
  };
  source_boundaries: Record<string, string> | null;
  semantic_boundaries: {
    brand_metric_label: string;
    collection_bucket_is_brand_ownership: boolean;
    market_share_supported: boolean;
    response_time_supported: boolean;
    roi_supported: boolean;
    created_at_utc_is_reddit_event_time?: true;
    canonical_event_time_field?: 'event_created_at_utc';
    comment_coverage_status_mapping?: Partial<Record<SnapshotCoverageGrade, SnapshotCommentCoverageStatus>>;
    thread_complete_means_no_observed_more_node_not_absolute_reddit_completeness?: true;
    global_product_category_imputed?: false;
    product_category_resolution_status?: 'governed_product_entity_resolver_v1';
    product_category_analysis_supported?: true;
    product_family_analysis_supported?: true;
    exact_spu_analysis_supported_only_for_approved_bindings?: true;
    product_entity_ledger_sha256?: string;
    unresolved_parent_business_label?: '待关联评论';
    unresolved_parent_comments_in_public_detail?: false;
    quarantined_comments_in_public_detail?: false;
    day_precision_midnight_imputed?: false;
    day_precision_display_contract?: 'YYYY-MM-DD';
    day_precision_created_at_utc_compatibility_value_is_calendar_date_not_instant?: true;
    metric_eligibility_owned_by_governed_metrics_dataset?: true;
  };
  privacy: {
    author_display: string;
    raw_author_fields_present: boolean;
    contact_patterns_redacted: boolean;
    known_archive_bots_excluded_from_voc_metrics?: boolean;
    author_linkage_excluded?: true;
    stable_pseudonym_exposed?: false;
  };
  tagging: {
    dictionary_version: string;
    dictionary_sha256?: string;
    labels_provisional: boolean;
    semantic_validation_run: boolean;
    entity_sentiment_overridden: boolean;
    matching_policy: string;
    provider_call?: false;
    spu_rule_gate?: 'governed_product_entity_ledger';
    product_entity_resolution?: SnapshotProductResolution;
  };
}

export interface SnapshotTagSummary {
  tag_id: string;
  name_cn: string;
  name_en: string;
  theme: string;
  tag_sentiment: string;
  post_entities: number;
  comment_entities: number;
  total_entities: number;
}

export interface SnapshotBrandMention {
  brand: string;
  posts: number;
  sample_mention_share: number;
}

export interface SnapshotAggregates {
  schema_version: string;
  headline: {
    unique_posts: number;
    linked_comments: number;
    quarantined_comments: number;
    stored_comments?: number;
    unresolved_parent_comments?: number;
    comments_in_voc_metrics: number;
    analysis_covered_posts: number;
    analysis_covered_comments: number;
    posts_with_rule_tags: number;
    comments_with_rule_tags_in_voc_metrics: number;
    posts_with_aspect_tags: number;
    comments_with_aspect_tags: number;
    comments_metric_eligibility_pending_base_projection?: number;
  };
  date_range: {
    posts: [string, string];
    comments: [string, string];
  };
  post_sentiment: Record<SnapshotSentiment, number>;
  comment_sentiment: Record<SnapshotSentiment, number>;
  post_topics: Record<string, number>;
  pain_points: Record<string, number>;
  subreddit_posts: Record<string, number>;
  subreddit_comments: Record<string, number>;
  monthly_posts: Record<string, number>;
  brand_sample_mentions: SnapshotBrandMention[];
  coverage_grade: Partial<Record<SnapshotCoverageGrade, number>>;
  count_completeness_status: Record<string, number>;
  parent_link_status: Record<string, number>;
  metric_notes: Record<string, string>;
  time_precision?: {
    posts: Partial<Record<'instant' | 'day', number>>;
    comments: Partial<Record<'instant' | 'day', number>>;
    day_precision_midnight_imputed: false;
  };
  metric_eligibility_status?: Record<string, number>;
  tagging: {
    dictionary_version: string;
    posts_with_rule_tags: number;
    comments_with_rule_tags: number;
    posts_with_aspect_tags: number;
    comments_with_aspect_tags: number;
    top_tags: SnapshotTagSummary[];
  };
}

export interface SnapshotTagRule {
  tag_id: string;
  name_cn: string;
  name_en: string;
  theme: string;
  sentiment: string;
  tag_scope: string;
}

export interface SnapshotTagDictionary {
  schema_version: string;
  dictionary_version: string;
  dictionary_sha256: string;
  rules: SnapshotTagRule[];
}

export interface RedditSnapshotCore {
  release: CurrentRelease;
  manifest: SnapshotManifest;
  aggregates: SnapshotAggregates;
  posts: SnapshotPost[];
  tagDictionary: SnapshotTagDictionary;
  tagRulesById: ReadonlyMap<string, SnapshotTagRule>;
}

export interface RedditSnapshotSummary {
  release: CurrentRelease;
  manifest: SnapshotManifest;
  aggregates: SnapshotAggregates;
}

export interface InsightsBoundaries {
  scope: string;
  labels_outside_promoted_set_provisional?: boolean;
  independent_human_review?: boolean;
  production_unchanged: boolean;
  provider_call: boolean;
  database_write: boolean;
  live_send: boolean;
  deploy?: boolean;
}

export interface InsightsAuditSummary {
  audited_tags?: number;
  reviewed_assignments: number | null;
  promoted_tags: number;
  held_tags: number;
  promoted_tag_ids: string[];
  held_tag_ids: string[];
  status: string;
}

export interface InsightsManifest {
  schema_version: string;
  dataset_version: string;
  delivery_mode: string;
  base_dataset_version: string;
  base_manifest_sha256: string;
  dictionary_version: string;
  dictionary_sha256: string;
  status: string;
  contract_extension?: 'reddit_voc_insights_manifest_v2';
  reports_dataset_version?: string;
  semantic_governance_version?: string;
  audit_summary: InsightsAuditSummary;
  files: Record<string, { bytes: number; sha256: string }>;
  boundaries: InsightsBoundaries;
}

export interface InsightsReviewMetrics {
  reviewed: number;
  correct: number;
  incorrect: number;
  ambiguous: number;
  label_precision: number;
  wilson_lower_bound_95: number;
  taxonomy_fit_rate: number;
  ambiguous_rate: number;
}

export interface InsightsDictionaryReference {
  aipl_node: string;
  consumer_card: string;
  intent_type: string;
  problem_type: string;
  story_lines: string;
}

export interface InsightsEvidenceExample {
  audit_id: string;
  entity_type: 'post' | 'comment';
  entity_id: string;
  reddit_id: string;
  post_id: string;
  subreddit: string | null;
  created_at_utc: string;
  source_stratum: string;
  evidence_keywords: string[];
  context_excerpt: string;
  review_reason_code: string;
}

export interface InsightsSignal {
  tag_id: string;
  name_cn: string;
  name_en: string;
  theme: string;
  matched_posts: number;
  matched_comments: number;
  matched_entities: number;
  review_metrics: InsightsReviewMetrics;
  dictionary_reference: InsightsDictionaryReference;
  evidence_examples: InsightsEvidenceExample[];
}

export interface InsightsHeldTag {
  tag_id: string;
  name_cn: string;
  theme: string;
  matched_entities: number;
  review_metrics: InsightsReviewMetrics;
  governance_review: {
    status: string;
    reason_code: string;
    note: string;
  };
  failed_checks: string[];
}

export type RiskEntityType = 'post' | 'comment';
export type RiskPriority = 'P0' | 'P1' | 'P2' | 'P3' | 'insufficient';
export type RiskComparisonStatus = 'comparable' | 'provisional_observed_sample' | 'unavailable';
export type RiskCoverageStatus = 'complete' | 'partial' | 'unavailable' | 'coverage_missing' | string;
export type ControlledBrandBinding =
  | 'brand_unbound'
  | 'competitor_sentence_bound'
  | 'momcozy_entity_reviewed'
  | 'momcozy_sentence_bound'
  | 'multi_brand_context';

export interface RiskObservedCount {
  metric: 'momcozy_brand_bound_observed_entity_count';
  value: number | null;
  unit: 'observed_entity';
  value_status: 'observed' | 'unavailable';
  observation_status?: RiskComparisonStatus;
  reason_codes?: string[];
}

export interface RiskShareMetric {
  metric: 'negative_momcozy_observed_entities_over_classified_momcozy_observed_entities';
  numerator: number | null;
  denominator: number | null;
  value: number | null;
  value_status: 'observed' | 'denominator_zero' | 'unavailable';
  observation_status?: RiskComparisonStatus;
  reason_codes?: string[];
}

export interface UnsupportedCombinedMetric {
  supported: false;
  reason: string;
  value: null;
}

export interface RiskMetricByEntity<T> {
  post: T;
  comment: T;
  combined: UnsupportedCombinedMetric;
}

export interface RiskComparison<T extends RiskObservedCount | RiskShareMetric = RiskObservedCount | RiskShareMetric> {
  metric_name: 'observed_count' | 'negative_evidence_share';
  comparison_type: string;
  entity_type: RiskEntityType;
  comparison_status: RiskComparisonStatus;
  reason_codes: string[];
  current: T;
  baseline: T | null;
  absolute_delta: number | null;
  relative_delta: number | null;
  delta_reason: string | null;
  direction_claim_supported: boolean;
}

export interface RiskEvidenceRef {
  entity_type: RiskEntityType;
  entity_id: string;
  post_id: string;
}

export interface RiskProductScopeIds {
  category: string[];
  product_family: string[];
  spu_exact: string[];
}

export interface RiskTheme {
  risk_theme_id: string;
  tag_id: string;
  name_cn: string;
  name_en: string;
  theme: string;
  risk_level: string;
  effective_priority: RiskPriority;
  evidence_gate: {
    status: 'passed' | 'insufficient';
    policy_version: string | null;
    reason_codes: string[];
    semantic_status: 'promoted' | 'provisional';
  };
  observed_entities: { post: number; comment: number };
  distinct_posts: number;
  communities: number;
  brand_binding_rate: number;
  brand_binding_counts: Record<ControlledBrandBinding, number>;
  sentence_bound_rate: number;
  event_window: { first_utc: string; last_utc: string };
  evidence_refs: RiskEvidenceRef[];
  evidence_ref_count_total: number;
  evidence_refs_truncated: boolean;
  product_scope_ids: RiskProductScopeIds;
  problem_type: string;
  intent_type: string;
  story_line: string;
}

export interface ProductScope {
  scope_id: string;
  scope_name_en: string;
  scope_name_cn: string;
  binding_level: 'category' | 'product_family' | 'spu_exact';
  metrics: RiskMetricByEntity<RiskShareMetric>;
  risk_priority_assignments: Record<RiskPriority, number>;
}

export interface ProductAnalysis {
  schema_version: 'reddit_voc_product_analysis_v1';
  decision_subject: 'momcozy';
  scope_order: ['category', 'product_family', 'spu_exact'];
  category: ProductScope[];
  product_family: ProductScope[];
  spu_exact: ProductScope[];
  coverage: Record<string, number | string | boolean | null>;
  interpretation_boundary: string;
}

export interface CompetitorContext {
  brand_id: string;
  brand_name: string;
  comparison_role: 'same_observed_sample_context';
  negative_evidence_share: RiskMetricByEntity<RiskShareMetric>;
  product_scope_ids: RiskProductScopeIds;
  interpretation_boundary: 'comparison_is_not_market_share_sov_penetration_or_sales';
}

export interface RiskWindow {
  start_utc: string;
  end_utc: string;
  start_local: string;
  end_local: string;
  timezone: string;
  interval: '[start,end)';
  is_closed: boolean;
  window_mode?: string;
}

export interface RiskCommandCenter {
  schema_version: 'reddit_voc_risk_command_center_v1';
  decision_subject: {
    brand_id: 'momcozy';
    brand_role: 'primary';
    competitors_role: 'comparison_context_only';
  };
  window: RiskWindow;
  primary_kpis: {
    high_priority_risk_themes: {
      value: number | null;
      status: string;
      included_priorities: ['P0', 'P1'];
      unit: string;
    };
    negative_evidence_share: RiskMetricByEntity<RiskShareMetric>;
    risk_momentum: {
      source_report: 'daily';
      previous_period: Record<RiskEntityType, RiskComparison<RiskShareMetric>>;
      year_over_year: Record<RiskEntityType, RiskComparison<RiskShareMetric>>;
      interpretation_boundary: string;
    };
  };
  priority_distribution: Record<RiskPriority, number>;
  risk_themes: RiskTheme[];
  competitor_context: CompetitorContext[];
  evidence_boundaries: Record<string, boolean>;
}

export interface ControlEvidence {
  schema_version: 'reddit_voc_control_evidence_v1';
  evidence_level: string;
  base_dataset_version: string;
  base_manifest_sha256: string;
  base_generated_at_utc: string;
  source_cutoffs: Record<string, string> | null;
  semantic_governance_version: string;
  coverage_ledger_version: string | null;
  risk_gate_policy_version: string | null;
  risk_gate_policy_status: string;
  recommendations_only: true;
  external_action_ledger_available: false;
  action_completion_supported: false;
  release_switch_executed: false;
  production_unchanged: true;
  provider_call: false;
  database_write: false;
  live_send: false;
  deploy: false;
}

export interface InsightsData {
  schema_version: string;
  dataset_version: string;
  base_dataset_version: string;
  generated_at_utc: string;
  headline: {
    audited_tags?: number;
    promoted_tags?: number;
    held_tags?: number;
    reviewed_assignments?: number;
    promoted_rule_assignments?: number;
    unique_posts_with_promoted_tags?: number;
    unique_comments_with_promoted_tags?: number;
    status?: 'unavailable';
    reason?: string;
  };
  signals: InsightsSignal[];
  reference_dimensions: Record<string, Record<string, number>>;
  held_tags: InsightsHeldTag[];
  interpretation_boundaries: {
    counts_are_rule_matched_entities_not_users?: boolean;
    promoted_means_sample_gate_passed_not_full_population_human_review?: boolean;
    consumer_card_is_reference_not_persona_id?: boolean;
    consumer_card_is_reference_not_user_identity?: boolean;
    persona_tags_generated?: boolean;
    persona_note?: string;
    market_share_supported: boolean;
    roi_supported: boolean;
    nps_supported?: boolean;
    response_time_supported?: boolean;
    trend_claim_supported?: boolean;
    posts_and_comments_separate_by_default?: boolean;
    combined_view_supported?: boolean;
    competitors_are_context_only?: boolean;
  };
  boundaries: InsightsBoundaries;
  legacy_compatibility?: {
    status: string;
    preserved_fields: string[];
    legacy_brand_binding_mapping_applied: false;
  };
  input_contract?: {
    status: 'passed';
    required_event_time_field: 'event_created_at_utc';
    brand_binding_values: ControlledBrandBinding[];
    post_count: number;
    comment_count: number;
    comment_coverage_counts: Record<string, number>;
    promoted_tag_ids: string[];
    held_tag_ids: string[];
  };
  risk_command_center?: RiskCommandCenter;
  product_analysis?: ProductAnalysis;
  report_booklets?: {
    schema_version: string;
    dataset_version: string;
    timezone: string;
    index: unknown;
  };
  control_evidence?: ControlEvidence;
}

export interface RiskInsightsData extends InsightsData {
  schema_version: 'reddit_voc_insights_v2';
  legacy_compatibility: NonNullable<InsightsData['legacy_compatibility']>;
  input_contract: NonNullable<InsightsData['input_contract']>;
  risk_command_center: RiskCommandCenter;
  product_analysis: ProductAnalysis;
  report_booklets: NonNullable<InsightsData['report_booklets']>;
  control_evidence: ControlEvidence;
}

export interface InsightsAuditTag {
  tag_id: string;
  promotion_status: 'promoted' | 'held';
  review_metrics: InsightsReviewMetrics;
  gate_checks: Record<string, boolean>;
  samples: Array<{
    audit_id: string;
    review: {
      label_verdict: 'correct' | 'incorrect' | 'ambiguous';
      taxonomy_fit: 'fit' | 'mismatch' | 'ambiguous';
      reason_code: string;
    };
  }>;
}

export interface InsightsSemanticAudit {
  schema_version: string;
  audit_version: string;
  base_dataset_version: string;
  base_manifest_sha256: string;
  dictionary_version: string;
  dictionary_sha256: string;
  source_audit?: Record<string, unknown> | null;
  sample_sha256: string;
  reviewer: {
    type: string;
    version: string;
    independent_human_review: boolean;
    review_policy: string;
  };
  quality_gate: {
    required_samples_per_tag: number;
    minimum_label_precision: number;
    minimum_wilson_lower_bound_95: number;
    minimum_taxonomy_fit_rate: number;
    maximum_ambiguous_rate: number;
    governance_status_required: string;
    promotion_scope: string;
  };
  summary: InsightsAuditSummary;
  tags: InsightsAuditTag[];
  boundaries: Partial<InsightsBoundaries> & {
    raw_review_samples_included?: boolean;
  };
}

export interface RedditInsightsSnapshot {
  core: RedditSnapshotCore;
  manifest: InsightsManifest;
  audit: InsightsSemanticAudit;
  insights: InsightsData;
}
