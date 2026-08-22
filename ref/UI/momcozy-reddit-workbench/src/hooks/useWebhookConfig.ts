import { useState, useEffect, useCallback } from 'react';
import type { WebhookConfig } from '../types';
import { getStorage, setStorage } from '../utils/storage';
import { appendDingTalkSign } from '../utils/dingtalkSign';
import { appendFeishuSign } from '../utils/feishuSign';

const STORAGE_KEY = 'momcozy_webhook_configs_v1';
const VERSION = 1;

const DEFAULT_CONFIGS: WebhookConfig[] = [
  {
    id: 'webhook-dingtalk',
    name: '钉钉机器人',
    provider: 'dingtalk',
    url: '',
    secret: '',
    enabled: false,
    channels: ['alert', 'system'],
    severityFilter: ['critical', 'warning'],
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'webhook-feishu',
    name: '飞书机器人',
    provider: 'feishu',
    url: '',
    secret: '',
    enabled: false,
    channels: ['alert', 'insight', 'system'],
    severityFilter: ['critical', 'warning', 'info'],
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
];

function loadConfigs(): WebhookConfig[] {
  const fallback = DEFAULT_CONFIGS;
  try {
    const parsed = getStorage<Array<Omit<WebhookConfig, 'secret'>>>(STORAGE_KEY, VERSION, []);
    if (!Array.isArray(parsed) || parsed.length === 0) return fallback;
    // 合并持久化数据与默认配置（secret 不恢复，仅内存保存）
    return parsed.map((c) => {
      const defaults = DEFAULT_CONFIGS.find((d) => d.id === c.id);
      return {
        ...(defaults ?? DEFAULT_CONFIGS[0]),
        ...c,
        secret: '',
      };
    });
  } catch {
    return fallback;
  }
}

function saveConfigs(configs: WebhookConfig[]) {
  const persisted = configs.map(({ secret: _, ...rest }) => rest);
  setStorage<Array<Omit<WebhookConfig, 'secret'>>>(STORAGE_KEY, VERSION, persisted);
}

export function useWebhookConfig() {
  const [configs, setConfigs] = useState<WebhookConfig[]>(loadConfigs);

  useEffect(() => {
    saveConfigs(configs);
  }, [configs]);

  const updateConfig = useCallback(
    (id: string, patch: Partial<WebhookConfig>) => {
      setConfigs((prev) =>
        prev.map((c) =>
          c.id === id ? { ...c, ...patch, updatedAt: new Date().toISOString() } : c
        )
      );
    },
    []
  );

  const toggleEnabled = useCallback((id: string) => {
    setConfigs((prev) =>
      prev.map((c) =>
        c.id === id
          ? { ...c, enabled: !c.enabled, updatedAt: new Date().toISOString() }
          : c
      )
    );
  }, []);

  const toggleChannel = useCallback((id: string, channel: WebhookConfig['channels'][number]) => {
    setConfigs((prev) =>
      prev.map((c) => {
        if (c.id !== id) return c;
        const has = c.channels.includes(channel);
        return {
          ...c,
          channels: has ? c.channels.filter((ch) => ch !== channel) : [...c.channels, channel],
          updatedAt: new Date().toISOString(),
        };
      })
    );
  }, []);

  const toggleSeverity = useCallback(
    (id: string, severity: WebhookConfig['severityFilter'][number]) => {
      setConfigs((prev) =>
        prev.map((c) => {
          if (c.id !== id) return c;
          const has = c.severityFilter.includes(severity);
          return {
            ...c,
            severityFilter: has
              ? c.severityFilter.filter((s) => s !== severity)
              : [...c.severityFilter, severity],
            updatedAt: new Date().toISOString(),
          };
        })
      );
    },
    []
  );

  const testConnection = useCallback(
    async (id: string): Promise<{ success: boolean; message: string }> => {
      const config = configs.find((c) => c.id === id);
      if (!config) return { success: false, message: '配置未找到' };
      if (!config.url.trim()) return { success: false, message: '请先填写 Webhook URL' };

      try {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 8000);

        const body = buildTestPayload(config.provider);

        let url = config.url;
        if (config.provider === 'dingtalk' && config.secret.trim()) {
          try {
            url = await appendDingTalkSign(url, config.secret.trim());
          } catch (signErr) {
            return {
              success: false,
              message: `加签失败: ${signErr instanceof Error ? signErr.message : String(signErr)}`,
            };
          }
        }
        if (config.provider === 'feishu' && config.secret.trim()) {
          try {
            url = await appendFeishuSign(url, config.secret.trim());
          } catch (signErr) {
            return {
              success: false,
              message: `加签失败: ${signErr instanceof Error ? signErr.message : String(signErr)}`,
            };
          }
        }

        const res = await fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
          signal: controller.signal,
        });

        clearTimeout(timeout);

        if (!res.ok) {
          return { success: false, message: `HTTP ${res.status}: ${res.statusText}` };
        }
        const text = await res.text();
        // DingTalk returns {"errcode":0, "errmsg":"ok"}
        if (text.includes('"errcode"') || text.includes('"errmsg"')) {
          try {
            const json = JSON.parse(text);
            if (json.errcode !== 0 && json.errcode !== undefined) {
              return { success: false, message: `${json.errmsg || '钉钉返回错误'}` };
            }
          } catch {}
        }
        return { success: true, message: '连接成功，机器人已响应' };
      } catch (err) {
        if (err instanceof Error && err.name === 'AbortError') {
          return { success: false, message: '连接超时，请检查 URL 是否可访问' };
        }
        return { success: false, message: `网络错误: ${err instanceof Error ? err.message : String(err)}` };
      }
    },
    [configs]
  );

  const addConfig = useCallback((provider: WebhookConfig['provider']) => {
    const id = `webhook-${provider}-${Date.now()}`;
    const newConfig: WebhookConfig = {
      id,
      name: provider === 'dingtalk' ? '钉钉机器人' : '飞书机器人',
      provider,
      url: '',
      secret: '',
      enabled: false,
      channels: ['alert', 'system'],
      severityFilter: ['critical', 'warning'],
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
    setConfigs((prev) => [...prev, newConfig]);
  }, []);

  const removeConfig = useCallback((id: string) => {
    setConfigs((prev) => prev.filter((c) => c.id !== id));
  }, []);

  return {
    configs,
    updateConfig,
    toggleEnabled,
    toggleChannel,
    toggleSeverity,
    testConnection,
    addConfig,
    removeConfig,
  };
}

function buildTestPayload(provider: WebhookConfig['provider']) {
  if (provider === 'dingtalk') {
    return {
      msgtype: 'markdown',
      markdown: {
        title: 'Momcozy 舆情工作台 - 测试消息',
        text: '### Momcozy 舆情工作台\n\n> 钉钉机器人连接测试成功 ✅\n\n您可以开始接收舆情通知。',
      },
      at: { isAtAll: false },
    };
  }
  return {
    msg_type: 'interactive',
    card: {
      header: {
        title: { tag: 'plain_text', content: 'Momcozy 舆情工作台 - 测试消息' },
        template: 'purple',
      },
      elements: [
        {
          tag: 'div',
          text: { tag: 'plain_text', content: '飞书机器人连接测试成功 ✅\n您可以开始接收舆情通知。' },
        },
      ],
    },
  };
}
