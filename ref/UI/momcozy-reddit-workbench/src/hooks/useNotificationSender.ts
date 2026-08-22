import { useCallback, useRef } from 'react';
import type { WebhookConfig, NotificationItem } from '../types';
import { appendDingTalkSign } from '../utils/dingtalkSign';
import { appendFeishuSign } from '../utils/feishuSign';

export interface SendResult {
  configId: string;
  success: boolean;
  message: string;
}

export interface NotificationSenderOptions {
  configs: WebhookConfig[];
  onResult?: (results: SendResult[]) => void;
}

function buildPayload(
  provider: WebhookConfig['provider'],
  item: NotificationItem
): Record<string, unknown> {
  const severityLabel = item.severity
    ? { critical: '严重', warning: '警告', info: '信息' }[item.severity]
    : '一般';

  const typeLabel = { alert: '警报', task: '任务', insight: '洞察', system: '系统' }[item.type];

  if (provider === 'dingtalk') {
    const text = [
      `## Momcozy Reddit 舆情工作台 - ${typeLabel}`,
      `**${item.title}**`,
      `> ${item.description}`,
      item.subreddit ? `- 社区：r/${item.subreddit}` : '',
      item.postTitle ? `- 帖子：${item.postTitle}` : '',
      `- 严重等级：${severityLabel}`,
      `- 时间：${item.time}`,
      item.actionUrl ? `\n[查看详情](${item.actionUrl})` : '',
    ]
      .filter(Boolean)
      .join('\n\n');

    return {
      msgtype: 'markdown',
      markdown: { title: `Momcozy ${typeLabel} - ${item.title}`, text },
      at: { isAtAll: item.severity === 'critical' },
    };
  }

  // Feishu
  const elements: Array<Record<string, unknown>> = [
    {
      tag: 'div',
      text: {
        tag: 'plain_text',
        content: `${item.description}`,
      },
    },
  ];

  if (item.subreddit) {
    elements.push({
      tag: 'div',
      text: {
        tag: 'plain_text',
        content: `社区：r/${item.subreddit}`,
      },
    });
  }
  if (item.postTitle) {
    elements.push({
      tag: 'div',
      text: {
        tag: 'plain_text',
        content: `帖子：${item.postTitle}`,
      },
    });
  }
  elements.push({
    tag: 'div',
    text: {
      tag: 'plain_text',
      content: `严重等级：${severityLabel} | 时间：${item.time}`,
    },
  });
  if (item.actionUrl) {
    elements.push({
      tag: 'action',
      actions: [
        {
          tag: 'button',
          text: { tag: 'plain_text', content: '查看详情' },
          type: 'primary',
          url: item.actionUrl,
        },
      ],
    });
  }

  return {
    msg_type: 'interactive',
    card: {
      header: {
        title: { tag: 'plain_text', content: `Momcozy ${typeLabel} - ${item.title}` },
        template: item.severity === 'critical' ? 'red' : item.severity === 'warning' ? 'orange' : 'purple',
      },
      elements,
    },
  };
}

export function useNotificationSender({ configs, onResult }: NotificationSenderOptions) {
  const resultsRef = useRef<SendResult[]>([]);

  const sendNotification = useCallback(
    async (item: NotificationItem): Promise<SendResult[]> => {
      const active = configs.filter((c) => c.enabled && c.url.trim());
      if (active.length === 0) return [];

      // Filter by channel type and severity
      const targets = active.filter((c) => {
        if (!c.channels.includes(item.type)) return false;
        if (item.severity && !c.severityFilter.includes(item.severity)) return false;
        return true;
      });

      if (targets.length === 0) return [];

      const results: SendResult[] = await Promise.all(
        targets.map(async (config) => {
          try {
            const controller = new AbortController();
            const timeout = setTimeout(() => controller.abort(), 10000);

            let url = config.url;
            if (config.provider === 'dingtalk' && config.secret.trim()) {
              try {
                url = await appendDingTalkSign(url, config.secret.trim());
              } catch (signErr) {
                return {
                  configId: config.id,
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
                  configId: config.id,
                  success: false,
                  message: `加签失败: ${signErr instanceof Error ? signErr.message : String(signErr)}`,
                };
              }
            }

            const res = await fetch(url, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(buildPayload(config.provider, item)),
              signal: controller.signal,
            });

            clearTimeout(timeout);

            if (!res.ok) {
              return { configId: config.id, success: false, message: `HTTP ${res.status}` };
            }

            const text = await res.text();
            if (text.includes('"errcode"')) {
              try {
                const json = JSON.parse(text);
                if (json.errcode !== 0 && json.errcode !== undefined) {
                  return { configId: config.id, success: false, message: json.errmsg || '钉钉返回错误' };
                }
              } catch {}
            }

            return { configId: config.id, success: true, message: '已推送' };
          } catch (err) {
            if (err instanceof Error && err.name === 'AbortError') {
              return { configId: config.id, success: false, message: '连接超时' };
            }
            return { configId: config.id, success: false, message: err instanceof Error ? err.message : '网络错误' };
          }
        })
      );

      resultsRef.current = results;
      onResult?.(results);
      return results;
    },
    [configs, onResult]
  );

  return { sendNotification, lastResults: resultsRef.current };
}

/** Utility to get a recent send-history from localStorage (stored as side-effect) */
export const WEBHOOK_HISTORY_KEY = 'momcozy_webhook_send_history';

export function getWebhookHistory(): SendResult[] {
  try {
    const raw = localStorage.getItem(WEBHOOK_HISTORY_KEY);
    return raw ? (JSON.parse(raw) as SendResult[]) : [];
  } catch {
    return [];
  }
}

export function appendWebhookHistory(results: SendResult[]) {
  try {
    const existing = getWebhookHistory();
    const entry = results.map((r) => ({ ...r, timestamp: Date.now() }));
    const merged = [...entry, ...existing].slice(0, 100);
    localStorage.setItem(WEBHOOK_HISTORY_KEY, JSON.stringify(merged));
  } catch {}
}
