import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { appendDingTalkSign, computeDingTalkSign } from '../dingtalkSign';

describe('dingtalkSign', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2024-01-15T10:00:00.000Z'));
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('returns original URL when secret is empty', async () => {
    const result = await appendDingTalkSign(
      'https://oapi.dingtalk.com/robot/send?access_token=abc',
      ''
    );
    expect(result).toBe('https://oapi.dingtalk.com/robot/send?access_token=abc');
  });

  it('appends sign to URL without query params', async () => {
    const mockSignature = new Uint8Array([1, 2, 3, 4, 5]);
    vi.stubGlobal('crypto', {
      subtle: {
        importKey: vi.fn().mockResolvedValue({}),
        sign: vi.fn().mockResolvedValue(mockSignature.buffer),
      },
    });

    const result = await appendDingTalkSign(
      'https://oapi.dingtalk.com/robot/send',
      'SEC123'
    );
    expect(result).toContain('timestamp=');
    expect(result).toContain('sign=');
    expect(result.startsWith('https://oapi.dingtalk.com/robot/send?')).toBe(true);
  });

  it('appends sign to URL with existing query params', async () => {
    const mockSignature = new Uint8Array([1, 2, 3, 4, 5]);
    vi.stubGlobal('crypto', {
      subtle: {
        importKey: vi.fn().mockResolvedValue({}),
        sign: vi.fn().mockResolvedValue(mockSignature.buffer),
      },
    });

    const result = await appendDingTalkSign(
      'https://oapi.dingtalk.com/robot/send?access_token=abc',
      'SEC123'
    );
    expect(result).toContain('access_token=abc');
    expect(result).toContain('timestamp=');
    expect(result).toContain('sign=');
    // 有 query 参数时应使用 & 连接
    expect(result.includes('&timestamp=')).toBe(true);
  });

  it('throws error when crypto.subtle is unavailable', async () => {
    vi.stubGlobal('crypto', undefined);

    await expect(computeDingTalkSign('SEC123')).rejects.toThrow('当前环境不支持 Web Crypto API');
  });

  it('computes consistent timestamp', async () => {
    const mockSignature = new Uint8Array([10, 20, 30]);
    vi.stubGlobal('crypto', {
      subtle: {
        importKey: vi.fn().mockResolvedValue({}),
        sign: vi.fn().mockResolvedValue(mockSignature.buffer),
      },
    });

    const result = await computeDingTalkSign('SEC123');
    expect(result.timestamp).toBe(String(Date.now()));
    expect(result.sign).toBeTruthy();
  });
});
