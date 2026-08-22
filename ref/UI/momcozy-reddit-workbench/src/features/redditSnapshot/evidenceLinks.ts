export interface SnapshotEvidenceLinkInput {
  postId: string;
  commentId?: string | null;
  releaseId: string;
  snapshotId: string;
  source: string;
}

export interface SnapshotEvidenceTarget {
  postId: string | null;
  commentId: string | null;
  releaseId: string | null;
  snapshotId: string | null;
  source: string | null;
}

function withThingPrefix(value: string, prefix: 't1_' | 't3_'): string {
  const trimmed = value.trim();
  if (!trimmed) return '';
  return trimmed.startsWith(prefix) ? trimmed : `${prefix}${trimmed}`;
}

export function normalizeSnapshotPostId(value: string): string {
  return withThingPrefix(value, 't3_');
}

export function normalizeSnapshotCommentId(value: string): string {
  return withThingPrefix(value, 't1_');
}

export function sameSnapshotEntityId(left: string, right: string): boolean {
  const normalize = (value: string) => value.trim().replace(/^t[13]_/, '');
  return normalize(left) === normalize(right);
}

export function buildSnapshotEvidenceHref(input: SnapshotEvidenceLinkInput): string {
  const postId = normalizeSnapshotPostId(input.postId);
  const params = new URLSearchParams();
  params.set('q', postId);
  params.set('post', postId);
  if (input.commentId) params.set('comment', normalizeSnapshotCommentId(input.commentId));
  params.set('release', input.releaseId);
  params.set('snapshot', input.snapshotId);
  params.set('from', input.source);
  return `/dashboard/search?${params.toString()}`;
}

export function readSnapshotEvidenceTarget(searchParams: URLSearchParams): SnapshotEvidenceTarget {
  const post = searchParams.get('post');
  return {
    postId: post ? normalizeSnapshotPostId(post) : null,
    commentId: searchParams.get('comment'),
    releaseId: searchParams.get('release'),
    snapshotId: searchParams.get('snapshot'),
    source: searchParams.get('from'),
  };
}

const SOURCE_LABELS: Record<string, string> = {
  dashboard: '品牌概览',
  reports: '舆情报告',
  insights: '洞察分析',
  personas: '用户画像',
  content: '案例内容',
  signals: '舆情信号',
  search: '帖子搜索',
};

export function snapshotEvidenceSourceLabel(source: string | null): string {
  if (!source) return '站内分析';
  return SOURCE_LABELS[source] ?? '站内分析';
}
