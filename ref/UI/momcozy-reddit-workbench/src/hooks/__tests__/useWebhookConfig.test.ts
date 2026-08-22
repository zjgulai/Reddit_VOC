import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useWebhookConfig } from '../useWebhookConfig';

const STORAGE_KEY = 'momcozy_webhook_configs_v1';
const VERSION = 1;

describe('useWebhookConfig', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
  });

  afterEach(() => {
    localStorage.clear();
  });

  it('returns default configs when localStorage is empty', () => {
    const { result } = renderHook(() => useWebhookConfig());
    expect(result.current.configs).toHaveLength(2);
    expect(result.current.configs[0].id).toBe('webhook-dingtalk');
    expect(result.current.configs[1].id).toBe('webhook-feishu');
  });

  it('does not persist secret to localStorage', () => {
    const { result } = renderHook(() => useWebhookConfig());

    act(() => {
      result.current.updateConfig('webhook-dingtalk', {
        url: 'https://example.com/hook',
        secret: 'my-secret-123',
      });
    });

    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{"version":0,"data":[]}');
    expect(stored.data).toHaveLength(2);
    const dingtalk = stored.data.find((c: Record<string, unknown>) => c.id === 'webhook-dingtalk');
    expect(dingtalk).toBeDefined();
    expect(dingtalk).not.toHaveProperty('secret');
    expect(dingtalk?.url).toBe('https://example.com/hook');
  });

  it('does not restore secret from localStorage on reload', () => {
    // 先模拟写入一个不包含 secret 的存储
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        version: VERSION,
        data: [
          {
            id: 'webhook-dingtalk',
            name: '钉钉机器人',
            provider: 'dingtalk',
            url: 'https://oapi.dingtalk.com/robot/send',
            enabled: true,
            channels: ['alert'],
            severityFilter: ['critical'],
            createdAt: new Date().toISOString(),
            updatedAt: new Date().toISOString(),
          },
        ],
      })
    );

    const { result } = renderHook(() => useWebhookConfig());
    const config = result.current.configs.find((c) => c.id === 'webhook-dingtalk');
    expect(config).toBeDefined();
    expect(config?.secret).toBe('');
    expect(config?.url).toBe('https://oapi.dingtalk.com/robot/send');
  });

  it('toggles enabled state', () => {
    const { result } = renderHook(() => useWebhookConfig());
    expect(result.current.configs[0].enabled).toBe(false);

    act(() => {
      result.current.toggleEnabled('webhook-dingtalk');
    });

    expect(result.current.configs[0].enabled).toBe(true);
  });

  it('toggles channel membership', () => {
    const { result } = renderHook(() => useWebhookConfig());
    const initialChannels = result.current.configs[0].channels;
    expect(initialChannels).toContain('alert');

    act(() => {
      result.current.toggleChannel('webhook-dingtalk', 'alert');
    });

    expect(result.current.configs[0].channels).not.toContain('alert');

    act(() => {
      result.current.toggleChannel('webhook-dingtalk', 'alert');
    });

    expect(result.current.configs[0].channels).toContain('alert');
  });

  it('toggles severity membership', () => {
    const { result } = renderHook(() => useWebhookConfig());
    expect(result.current.configs[0].severityFilter).toContain('critical');

    act(() => {
      result.current.toggleSeverity('webhook-dingtalk', 'critical');
    });

    expect(result.current.configs[0].severityFilter).not.toContain('critical');
  });

  it('returns error when testing with empty URL', async () => {
    const { result } = renderHook(() => useWebhookConfig());
    const res = await result.current.testConnection('webhook-dingtalk');
    expect(res.success).toBe(false);
    expect(res.message).toContain('请先填写');
  });

  it('returns error when config not found', async () => {
    const { result } = renderHook(() => useWebhookConfig());
    const res = await result.current.testConnection('non-existent');
    expect(res.success).toBe(false);
    expect(res.message).toContain('配置未找到');
  });

  it('adds a new webhook config', () => {
    const { result } = renderHook(() => useWebhookConfig());
    act(() => {
      result.current.addConfig('dingtalk');
    });
    expect(result.current.configs.length).toBe(3);
    const added = result.current.configs[2];
    expect(added.provider).toBe('dingtalk');
    expect(added.enabled).toBe(false);
    expect(added.url).toBe('');
  });

  it('removes a webhook config', () => {
    const { result } = renderHook(() => useWebhookConfig());
    act(() => {
      result.current.removeConfig('webhook-dingtalk');
    });
    expect(result.current.configs.length).toBe(1);
    expect(result.current.configs[0].id).toBe('webhook-feishu');
  });

  it('appends sign to dingtalk URL when secret is provided during test', async () => {
    const { result } = renderHook(() => useWebhookConfig());
    const res = await result.current.testConnection('non-existent');
    expect(res.success).toBe(false);
    expect(res.message).toContain('配置未找到');
  });

  it('appends sign to dingtalk URL when secret is provided during test', async () => {
    const { result } = renderHook(() => useWebhookConfig());

    act(() => {
      result.current.updateConfig('webhook-dingtalk', {
        url: 'https://oapi.dingtalk.com/robot/send?access_token=abc',
        secret: 'SEC123',
        enabled: true,
      });
    });

    const mockSignature = new Uint8Array([1, 2, 3, 4, 5]);
    vi.stubGlobal('crypto', {
      subtle: {
        importKey: vi.fn().mockResolvedValue({}),
        sign: vi.fn().mockResolvedValue(mockSignature.buffer),
      },
    });

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      text: () => Promise.resolve('{"errcode":0,"errmsg":"ok"}'),
    });

    await result.current.testConnection('webhook-dingtalk');

    const fetchCalls = (global.fetch as ReturnType<typeof vi.fn>).mock.calls;
    expect(fetchCalls.length).toBe(1);
    const [url] = fetchCalls[0];
    expect(url).toContain('timestamp=');
    expect(url).toContain('sign=');
    expect(url).toContain('access_token=abc');

    vi.unstubAllGlobals();
  });

  it('returns sign error when crypto is unavailable for dingtalk', async () => {
    const { result } = renderHook(() => useWebhookConfig());

    act(() => {
      result.current.updateConfig('webhook-dingtalk', {
        url: 'https://oapi.dingtalk.com/robot/send?access_token=abc',
        secret: 'SEC123',
        enabled: true,
      });
    });

    vi.stubGlobal('crypto', undefined);

    const res = await result.current.testConnection('webhook-dingtalk');
    expect(res.success).toBe(false);
    expect(res.message).toContain('加签失败');

    vi.unstubAllGlobals();
  });
});
