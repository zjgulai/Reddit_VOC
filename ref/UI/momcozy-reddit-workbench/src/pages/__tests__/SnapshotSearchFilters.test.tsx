import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { isMomcozyPost } from '../../features/redditSnapshot/operational';
import { validateCurrentRelease } from '../../features/redditSnapshot/release';
import { loadCommentsForPost, validateSnapshotCore } from '../../features/redditSnapshot/service';
import type {
  RedditSnapshotCore,
  SnapshotAggregates,
  SnapshotComment,
  SnapshotManifest,
  SnapshotPost,
  SnapshotTagDictionary,
} from '../../features/redditSnapshot/types';
import { useRedditSnapshot } from '../../features/redditSnapshot/useRedditSnapshot';
import SnapshotSearch from '../SnapshotSearch';

vi.mock('../../features/redditSnapshot/useRedditSnapshot', () => ({
  useRedditSnapshot: vi.fn(),
}));
vi.mock('../../features/redditSnapshot/service', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../features/redditSnapshot/service')>();
  return { ...actual, loadCommentsForPost: vi.fn() };
});

const publicDirectory = resolve(process.cwd(), 'public');
const release = validateCurrentRelease(JSON.parse(
  readFileSync(resolve(publicDirectory, 'data/reddit-voc/current-release.json'), 'utf8'),
));
const snapshotDirectory = resolve(publicDirectory, 'data/reddit-voc', release.datasets.base.dataset_version);

function readJson<T>(filename: string): T {
  return JSON.parse(readFileSync(resolve(snapshotDirectory, filename), 'utf8')) as T;
}

function hasComparisonBrand(post: SnapshotPost): boolean {
  return post.brand_binding === 'competitor_sentence_bound'
    || post.brand_binding === 'multi_brand_context'
    || post.mentioned_brands.some((brand) => brand.trim().toLowerCase() !== 'momcozy');
}

let snapshot: RedditSnapshotCore;

function DashboardRoute() {
  const navigate = useNavigate();
  return <button type="button" onClick={() => navigate(-1)}>返回搜索</button>;
}

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
  vi.mocked(loadCommentsForPost).mockResolvedValue([]);
});

describe('SnapshotSearch operational filters', () => {
  it('exposes brand, product hierarchy, severity, tag and interaction filters from the real snapshot', () => {
    render(<MemoryRouter initialEntries={['/dashboard/search']}><SnapshotSearch /></MemoryRouter>);

    expect(screen.getByLabelText('品牌筛选')).toBeInTheDocument();
    expect(screen.getByLabelText('严重度筛选')).toBeInTheDocument();
    expect(screen.getByLabelText('品类筛选')).toBeInTheDocument();
    expect(screen.getByLabelText('产品族筛选')).toBeInTheDocument();
    expect(screen.getByLabelText('SPU 筛选')).toBeInTheDocument();
    expect(screen.getByLabelText('标签筛选')).toBeInTheDocument();
    expect(screen.getByLabelText('最低 Score')).toBeInTheDocument();
    expect(screen.getByLabelText('最低关联评论数')).toBeInTheDocument();
  });

  it('combines Momcozy, product category and interaction thresholds without blanking the corpus', () => {
    const categoryBinding = snapshot.posts
      .find((post) => isMomcozyPost(post) && (post.product_bindings?.length ?? 0) > 0)
      ?.product_bindings?.[0];
    expect(categoryBinding).toBeDefined();

    render(<MemoryRouter initialEntries={['/dashboard/search']}><SnapshotSearch /></MemoryRouter>);

    fireEvent.change(screen.getByLabelText('品牌筛选'), { target: { value: 'momcozy' } });
    const momcozyCount = snapshot.posts.filter(isMomcozyPost).length;
    expect(screen.getByText(/找到/)).toHaveTextContent(`找到 ${momcozyCount} 条真实帖子`);

    fireEvent.change(screen.getByLabelText('品类筛选'), { target: { value: categoryBinding!.category.id } });
    const categoryCount = snapshot.posts.filter((post) => (
      isMomcozyPost(post)
      && (post.product_bindings ?? []).some((binding) => binding.category.id === categoryBinding!.category.id)
    )).length;
    expect(screen.getByText(/找到/)).toHaveTextContent(`找到 ${categoryCount} 条真实帖子`);

    fireEvent.change(screen.getByLabelText('最低 Score'), { target: { value: '5' } });
    const highInteractionCount = snapshot.posts.filter((post) => (
      isMomcozyPost(post)
      && (post.product_bindings ?? []).some((binding) => binding.category.id === categoryBinding!.category.id)
      && post.score >= 5
    )).length;
    expect(screen.getByText(/找到/)).toHaveTextContent(`找到 ${highInteractionCount} 条真实帖子`);
    expect(screen.getByRole('button', { name: '清除全部筛选' })).toBeInTheDocument();
  });

  it('uses explicit non-Momcozy mentions or comparison bindings for the comparison view', () => {
    render(<MemoryRouter initialEntries={['/dashboard/search']}><SnapshotSearch /></MemoryRouter>);

    fireEvent.change(screen.getByLabelText('品牌筛选'), { target: { value: 'comparison' } });
    expect(screen.getByText(/找到/)).toHaveTextContent(
      `找到 ${snapshot.posts.filter(hasComparisonBrand).length} 条真实帖子`,
    );
  });

  it('filters by an individual competitor brand and preserves its URL value', () => {
    const brand = snapshot.posts
      .flatMap((post) => post.mentioned_brands)
      .find((value) => value.trim().toLowerCase() !== 'momcozy');
    expect(brand).toBeDefined();
    const normalized = brand!.trim().toLowerCase().replace(/\s+/g, ' ');
    const expectedCount = snapshot.posts.filter((post) => (
      post.mentioned_brands.some((value) => value.trim().toLowerCase().replace(/\s+/g, ' ') === normalized)
    )).length;

    render(<MemoryRouter initialEntries={['/dashboard/search']}><SnapshotSearch /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText('品牌筛选'), { target: { value: `brand:${normalized}` } });

    expect(screen.getByLabelText('品牌筛选')).toHaveValue(`brand:${normalized}`);
    expect(screen.getByText(/找到/)).toHaveTextContent(`找到 ${expectedCount} 条真实帖子`);
  });

  it('hydrates every operational filter from the URL contract', () => {
    const binding = snapshot.posts.flatMap((post) => post.product_bindings ?? [])
      .find((item) => item.product_family && item.exact_spu);
    const taggedPost = snapshot.posts.find((post) => post.tagging.tag_ids.length > 0);
    expect(binding).toBeDefined();
    expect(taggedPost).toBeDefined();
    const params = new URLSearchParams({
      sentiment: 'negative',
      brand: 'momcozy',
      severity: 'high',
      topic: snapshot.posts[0].analysis.topic,
      subreddit: snapshot.posts[0].subreddit,
      category: binding!.category.id,
      family: binding!.product_family!.id,
      spu: binding!.exact_spu!.spu_id,
      tag: taggedPost!.tagging.tag_ids[0],
      minScore: '5',
      minComments: '1',
      page: '2',
    });

    render(<MemoryRouter initialEntries={[`/dashboard/search?${params.toString()}`]}><SnapshotSearch /></MemoryRouter>);

    expect(screen.getByLabelText('情感筛选')).toHaveValue('negative');
    expect(screen.getByLabelText('品牌筛选')).toHaveValue('momcozy');
    expect(screen.getByLabelText('严重度筛选')).toHaveValue('high');
    expect(screen.getByLabelText('主题筛选')).toHaveValue(snapshot.posts[0].analysis.topic);
    expect(screen.getByLabelText('社区筛选')).toHaveValue(snapshot.posts[0].subreddit);
    expect(screen.getByLabelText('品类筛选')).toHaveValue(binding!.category.id);
    expect(screen.getByLabelText('产品族筛选')).toHaveValue(binding!.product_family!.id);
    expect(screen.getByLabelText('SPU 筛选')).toHaveValue(binding!.exact_spu!.spu_id);
    expect(screen.getByLabelText('标签筛选')).toHaveValue(taggedPost!.tagging.tag_ids[0]);
    expect(screen.getByLabelText('最低 Score')).toHaveValue('5');
    expect(screen.getByLabelText('最低关联评论数')).toHaveValue('1');
  });

  it('consumes the complete evidence lineage and automatically opens the requested post and comment', async () => {
    const post = snapshot.posts.find((item) => item.linked_comment_count > 0) ?? snapshot.posts[0];
    const targetComment: SnapshotComment = {
      comment_id: 't1_target_comment',
      reddit_id: 'target_comment',
      post_id: post.post_id,
      parent_id: post.post_id,
      body: 'Target comment body for evidence navigation.',
      created_at_utc: post.created_at_utc,
      score: 8,
      depth: 0,
      deleted_or_removed: false,
      is_bot: false,
      include_in_voc_metrics: true,
      analysis: post.analysis,
      tagging: post.tagging,
      evidence_id: 'comment:target_comment',
    };
    vi.mocked(loadCommentsForPost).mockResolvedValue([targetComment]);
    const params = new URLSearchParams({
      q: post.post_id,
      post: post.post_id,
      comment: targetComment.comment_id,
      release: snapshot.release.release_id,
      snapshot: snapshot.manifest.dataset_version,
      from: 'reports',
    });

    render(
      <MemoryRouter initialEntries={[`/dashboard/search?${params.toString()}`]}>
        <SnapshotSearch />
      </MemoryRouter>,
    );

    expect(await screen.findByRole('dialog', { name: post.title })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: '证据定位结果' })).toHaveTextContent('已从舆情报告定位到这条帖子及对应评论');
    expect(await screen.findByText(targetComment.body)).toBeInTheDocument();
    expect(document.querySelector('[data-targeted-comment="true"]')).toHaveTextContent('已定位评论');
    expect(loadCommentsForPost).toHaveBeenCalledWith(post.post_id);
  });

  it('renders hash-bound DeepSeek Chinese translations before the English originals in post detail', async () => {
    const sourcePost = snapshot.posts.find((item) => item.linked_comment_count > 0) ?? snapshot.posts[0];
    const translatedPost: SnapshotPost = {
      ...sourcePost,
      translation: {
        title_zh: '中文帖子标题',
        content_zh: '这是帖子正文的中文翻译。',
        title_input_sha256: 'a'.repeat(64),
        content_input_sha256: 'b'.repeat(64),
        title_quality_status: 'deterministic_passed_unreviewed',
        content_quality_status: 'deterministic_passed_unreviewed',
        provider: 'deepseek',
        model: 'deepseek-v4-flash',
        semantic_validation: 'not_run',
        independent_human_review: false,
      },
    };
    const translatedSnapshot = {
      ...snapshot,
      posts: snapshot.posts.map((post) => post.post_id === translatedPost.post_id ? translatedPost : post),
    };
    const translatedComment: SnapshotComment = {
      comment_id: 'translated_comment',
      reddit_id: 'translated_comment',
      post_id: translatedPost.post_id,
      parent_id: translatedPost.post_id,
      body: 'Original English comment.',
      created_at_utc: translatedPost.created_at_utc,
      score: 5,
      depth: 0,
      deleted_or_removed: false,
      is_bot: false,
      include_in_voc_metrics: true,
      analysis: translatedPost.analysis,
      tagging: translatedPost.tagging,
      evidence_id: 'comment:translated_comment',
      translation: {
        body_zh: '评论的中文翻译。',
        input_sha256: 'c'.repeat(64),
        quality_status: 'deterministic_passed_unreviewed',
        provider: 'deepseek',
        model: 'deepseek-v4-flash',
        semantic_validation: 'not_run',
        independent_human_review: false,
      },
    };
    vi.mocked(useRedditSnapshot).mockReturnValue({ data: translatedSnapshot, error: null, isLoading: false });
    vi.mocked(loadCommentsForPost).mockResolvedValue([translatedComment]);

    render(
      <MemoryRouter initialEntries={[`/dashboard/search?q=${translatedPost.post_id}&post=${translatedPost.post_id}`]}>
        <SnapshotSearch />
      </MemoryRouter>,
    );

    expect(await screen.findByRole('dialog', { name: '中文帖子标题' })).toBeInTheDocument();
    expect(screen.getByText('这是帖子正文的中文翻译。')).toBeInTheDocument();
    expect(await screen.findByText('评论的中文翻译。')).toBeInTheDocument();
    expect(screen.getByText('DeepSeek 中文翻译 · 确定性校验通过 · 未经人工复核')).toBeInTheDocument();
    expect(screen.getByText(`英文原题：${translatedPost.title}`)).toBeInTheDocument();
    expect(screen.getAllByText('查看英文原文')).toHaveLength(2);
  });

  it('restores all URL-backed filters and the page after leaving search and using browser back', () => {
    const negativeCount = snapshot.posts.filter((post) => post.analysis.sentiment_label === 'negative').length;
    expect(negativeCount).toBeGreaterThan(12);
    render(
      <MemoryRouter initialEntries={['/dashboard/search']}>
        <Routes>
          <Route path="/dashboard/search" element={<SnapshotSearch />} />
          <Route path="/dashboard" element={<DashboardRoute />} />
        </Routes>
      </MemoryRouter>,
    );

    fireEvent.change(screen.getByLabelText('情感筛选'), { target: { value: 'negative' } });
    fireEvent.change(screen.getByLabelText('最低 Score'), { target: { value: '1' } });
    const nextPage = screen.getByRole('button', { name: /下一页/ });
    fireEvent.click(nextPage);
    fireEvent.click(screen.getAllByRole('link', { name: '概览' })[0]);
    fireEvent.click(screen.getByRole('button', { name: '返回搜索' }));

    expect(screen.getByLabelText('情感筛选')).toHaveValue('negative');
    expect(screen.getByLabelText('最低 Score')).toHaveValue('1');
    expect(screen.getByText(/第 2 \/ /)).toBeInTheDocument();
  }, 10_000);
});
