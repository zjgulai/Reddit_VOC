import { describe, expect, it } from 'vitest';
import {
  buildSnapshotEvidenceHref,
  readSnapshotEvidenceTarget,
  sameSnapshotEntityId,
} from '../evidenceLinks';

describe('snapshot evidence links', () => {
  it('preserves the complete release, snapshot, source, post and comment lineage', () => {
    const href = buildSnapshotEvidenceHref({
      postId: 'abc123',
      commentId: 'def456',
      releaseId: 'reddit_voc_release_example',
      snapshotId: 'reddit_voc_personas_example',
      source: 'personas',
    });
    const url = new URL(href, 'http://localhost');

    expect(url.pathname).toBe('/dashboard/search');
    expect(Object.fromEntries(url.searchParams)).toEqual({
      q: 't3_abc123',
      post: 't3_abc123',
      comment: 't1_def456',
      release: 'reddit_voc_release_example',
      snapshot: 'reddit_voc_personas_example',
      from: 'personas',
    });
    expect(readSnapshotEvidenceTarget(url.searchParams)).toEqual({
      postId: 't3_abc123',
      commentId: 't1_def456',
      releaseId: 'reddit_voc_release_example',
      snapshotId: 'reddit_voc_personas_example',
      source: 'personas',
    });
  });

  it('matches Reddit thing IDs with or without their type prefix', () => {
    expect(sameSnapshotEntityId('t3_abc123', 'abc123')).toBe(true);
    expect(sameSnapshotEntityId('t1_def456', 'def456')).toBe(true);
    expect(sameSnapshotEntityId('t3_abc123', 't3_other')).toBe(false);
  });
});
