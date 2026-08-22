import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  CASEBOOK_PUBLIC_BASE_PATH,
  CASEBOOK_PUBLIC_MANIFEST_SHA256,
  loadRedditCasebook,
  resetRedditCasebookCacheForTests,
  validatePublicCasebookData,
  validatePublicCasebookManifest,
} from '../casebook';

const publicDirectory = resolve(process.cwd(), 'public');
const casebookDirectory = resolve(publicDirectory, CASEBOOK_PUBLIC_BASE_PATH.slice(1));

function createFetch(tamperPath?: string) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const pathname = new URL(String(input), 'http://localhost').pathname;
    const original = readFileSync(resolve(publicDirectory, pathname.slice(1)), 'utf8');
    const body = pathname === tamperPath
      ? (pathname.endsWith('/manifest.json') ? `${original} ` : original.replace('C2', 'C3'))
      : original;
    return { ok: true, status: 200, text: async () => body } as Response;
  });
}

afterEach(() => {
  resetRedditCasebookCacheForTests();
  vi.unstubAllGlobals();
});

describe('public governance casebook contract', () => {
  it('validates and loads the pinned PII-free public projection', async () => {
    const manifest = validatePublicCasebookManifest(JSON.parse(readFileSync(resolve(casebookDirectory, 'manifest.json'), 'utf8')));
    const data = validatePublicCasebookData(JSON.parse(readFileSync(resolve(casebookDirectory, 'casebook.json'), 'utf8')));
    vi.stubGlobal('fetch', createFetch());

    const loaded = await loadRedditCasebook();

    expect(manifest.source_casebook_manifest_sha256).toBe('c0822ca4962f537b126090bc43104d5bbf8735df8e48ab3fd2936470229f93b4');
    expect(data.dossiers[0].title).toBe('Momcozy 社区信任与疑似非自然推广治理事件');
    expect(loaded.data.dossiers[0].assessment).toMatchObject({ commercial_relation: 'C2', integrity_level: 'I3', brand_control_confirmed: false });
    expect(loaded.data.dossiers[0].stages.map((stage) => stage.label)).toEqual(['洞察', '证据', '行动', '监测', '复盘']);
    expect(createFetch).toBeDefined();
  });

  it('fails closed when the pinned manifest or casebook bytes change', async () => {
    vi.stubGlobal('fetch', createFetch(`${CASEBOOK_PUBLIC_BASE_PATH}/casebook.json`));
    await expect(loadRedditCasebook()).rejects.toThrow('casebook.json SHA-256不一致');

    resetRedditCasebookCacheForTests();
    vi.stubGlobal('fetch', createFetch(`${CASEBOOK_PUBLIC_BASE_PATH}/manifest.json`));
    await expect(loadRedditCasebook()).rejects.toThrow('casebook manifest SHA-256不一致');
    expect(CASEBOOK_PUBLIC_MANIFEST_SHA256).toMatch(/^[a-f0-9]{64}$/);
  });
});
