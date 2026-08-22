import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../../App';
import { validateCurrentRelease } from '../../features/redditSnapshot/release';
import { validateSnapshotCore } from '../../features/redditSnapshot/service';
import type {
  SnapshotAggregates,
  SnapshotManifest,
  SnapshotPost,
  SnapshotTagDictionary,
} from '../../features/redditSnapshot/types';
import { useRedditSnapshot } from '../../features/redditSnapshot/useRedditSnapshot';

vi.mock('../../features/redditSnapshot/useRedditSnapshot', () => ({
  useRedditSnapshot: vi.fn(),
}));

const publicDirectory = resolve(process.cwd(), 'public');
const release = validateCurrentRelease(JSON.parse(
  readFileSync(resolve(publicDirectory, 'data/reddit-voc/current-release.json'), 'utf8'),
));
const snapshotDirectory = resolve(
  publicDirectory,
  'data/reddit-voc',
  release.datasets.base.dataset_version,
);

function readJson<T>(filename: string): T {
  return JSON.parse(readFileSync(resolve(snapshotDirectory, filename), 'utf8')) as T;
}

const snapshot = validateSnapshotCore(
  readJson<SnapshotManifest>('manifest-public.json'),
  readJson<SnapshotAggregates>('aggregates-public.json'),
  readJson<SnapshotPost[]>('posts-public.json'),
  readJson<SnapshotTagDictionary>('tag-dictionary-public.json'),
  release,
);

describe('production snapshot workspaces', () => {
  beforeEach(() => {
    vi.mocked(useRedditSnapshot).mockReturnValue({ data: snapshot, error: null, isLoading: false });
  });

  it.each([
    ['/dashboard/ugc-showcase', 'Momcozy 高价值内容', '真实内容机会'],
    ['/dashboard/messages', 'Momcozy 舆情信号', '优先舆情信号'],
    ['/dashboard/settings', '数据与指标口径', '当前真实数据范围'],
  ])('loads %s from the current release instead of a feature gate', async (path, heading, evidenceLabel) => {
    window.history.replaceState({}, '', path);

    render(<App />);

    expect(await screen.findByRole('heading', { name: heading }, { timeout: 5_000 })).toBeInTheDocument();
    expect(screen.getByText(evidenceLabel)).toBeInTheDocument();
    expect(screen.getByText('版本完整性 · 已验证')).toBeInTheDocument();
    expect(document.querySelector('[data-ui-severity="error"]')).not.toBeInTheDocument();
    expect(document.querySelectorAll('[aria-label$="指标说明"]').length).toBeGreaterThan(0);
    expect(document.body).not.toHaveTextContent('消息中心暂不展示数据');
    expect(document.body).not.toHaveTextContent('UGC 素材库暂不展示数据');
    expect(document.body).not.toHaveTextContent('生产设置当前为只读');
  });

  it('shows conserved V3 totals and the active release on the metric definitions page', async () => {
    window.history.replaceState({}, '', '/dashboard/settings');
    render(<App />);

    expect((await screen.findAllByText(release.release_id)).length).toBeGreaterThan(0);
    expect(screen.getByText(snapshot.manifest.canonical_counts.posts.toLocaleString('zh-CN'))).toBeInTheDocument();
    expect(screen.getByText(snapshot.manifest.canonical_counts.stored_comments.toLocaleString('zh-CN'))).toBeInTheDocument();
    expect(screen.getByText(snapshot.manifest.canonical_counts.linked_comments.toLocaleString('zh-CN'))).toBeInTheDocument();
    expect(screen.getAllByText((snapshot.manifest.canonical_counts.unresolved_parent_comments ?? 0).toLocaleString('zh-CN')).length).toBeGreaterThan(0);
    expect(screen.getByRole('heading', { name: '帖子、评论与帖子+评论关系' })).toBeInTheDocument();
  });
});
