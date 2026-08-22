import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { highValueContent } from '../../features/redditSnapshot/operational';
import { validateCurrentRelease } from '../../features/redditSnapshot/release';
import { validateSnapshotCore } from '../../features/redditSnapshot/service';
import type {
  RedditSnapshotCore,
  SnapshotAggregates,
  SnapshotManifest,
  SnapshotPost,
  SnapshotTagDictionary,
} from '../../features/redditSnapshot/types';
import { useRedditSnapshot } from '../../features/redditSnapshot/useRedditSnapshot';
import SnapshotWorkspace from '../SnapshotWorkspace';

vi.mock('../../features/redditSnapshot/useRedditSnapshot', () => ({
  useRedditSnapshot: vi.fn(),
}));

const publicDirectory = resolve(process.cwd(), 'public');
const release = validateCurrentRelease(JSON.parse(
  readFileSync(resolve(publicDirectory, 'data/reddit-voc/current-release.json'), 'utf8'),
));
const snapshotDirectory = resolve(publicDirectory, 'data/reddit-voc', release.datasets.base.dataset_version);

function readJson<T>(filename: string): T {
  return JSON.parse(readFileSync(resolve(snapshotDirectory, filename), 'utf8')) as T;
}

function SearchRoute() {
  const navigate = useNavigate();
  return <button type="button" onClick={() => navigate(-1)}>返回内容池</button>;
}

let snapshot: RedditSnapshotCore;

beforeAll(() => {
  snapshot = validateSnapshotCore(
    readJson<SnapshotManifest>('manifest-public.json'),
    readJson<SnapshotAggregates>('aggregates-public.json'),
    readJson<SnapshotPost[]>('posts-public.json'),
    readJson<SnapshotTagDictionary>('tag-dictionary-public.json'),
    release,
  );
});

beforeEach(() => {
  vi.mocked(useRedditSnapshot).mockReturnValue({ data: snapshot, error: null, isLoading: false });
});

describe('SnapshotWorkspace URL state', () => {
  it('restores the content sentiment after opening evidence and using browser back', () => {
    expect(highValueContent(snapshot).some((post) => post.analysis.sentiment_label === 'negative')).toBe(true);
    const { container } = render(
      <MemoryRouter initialEntries={['/dashboard/ugc-showcase']}>
        <Routes>
          <Route path="/dashboard/ugc-showcase" element={<SnapshotWorkspace workspace="content" />} />
          <Route path="/dashboard/search" element={<SearchRoute />} />
        </Routes>
      </MemoryRouter>,
    );

    fireEvent.change(screen.getByLabelText('内容情感筛选'), { target: { value: 'negative' } });
    const evidenceLink = container.querySelector<HTMLAnchorElement>('a[href*="from=content"]');
    if (!evidenceLink) throw new Error('expected content evidence link');
    fireEvent.click(evidenceLink);
    fireEvent.click(screen.getByRole('button', { name: '返回内容池' }));

    expect(screen.getByLabelText('内容情感筛选')).toHaveValue('negative');
  });
});
