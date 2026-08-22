import { useState, useEffect, useRef, useCallback } from 'react';
import { getStorage, setStorage } from '../utils/storage';
import type { WebhookConfig, NotificationItem } from '../types';
import type { SendResult } from './useNotificationSender';

export interface WebhookPollStatus {
  /** 是否正在轮询中 */
  isPolling: boolean;
  /** 上次轮询时间 ISO 字符串 */
  lastPollAt: string | null;
  /** 距离下次轮询的秒数 */
  nextPollIn: number;
  /** 本次轮询待推送数量 */
  pendingCount: number;
  /** 上次轮询错误信息 */
  lastError: string | null;
  /** 已推送通知 ID 集合 */
  pushedIds: Set<string>;
  /** 手动触发轮询 */
  triggerPoll: () => Promise<void>;
}

const STORAGE_KEY = 'momcozy_webhook_pushed_ids_v1';
const VERSION = 1;
const INTERVAL_MS = 5 * 60 * 1000; // 5 minutes

function loadPushedIds(): Set<string> {
  return new Set(getStorage<string[]>(STORAGE_KEY, VERSION, []));
}

function savePushedIds(ids: Set<string>) {
  setStorage<string[]>(STORAGE_KEY, VERSION, [...ids]);
}

export function useWebhookPoller({
  configs,
  notifications,
  sendNotification,
  enabled = true,
}: {
  configs: WebhookConfig[];
  notifications: NotificationItem[];
  sendNotification: (item: NotificationItem) => Promise<SendResult[]>;
  enabled?: boolean;
}): WebhookPollStatus {
  const [isPolling, setIsPolling] = useState(false);
  const [lastPollAt, setLastPollAt] = useState<string | null>(null);
  const [nextPollIn, setNextPollIn] = useState(0);
  const [pendingCount, setPendingCount] = useState(0);
  const [lastError, setLastError] = useState<string | null>(null);
  const pushedIdsRef = useRef<Set<string>>(loadPushedIds());
  const pollingLockRef = useRef(false);

  const configsRef = useRef(configs);
  const notificationsRef = useRef(notifications);
  const sendRef = useRef(sendNotification);
  const enabledRef = useRef(enabled);

  configsRef.current = configs;
  notificationsRef.current = notifications;
  sendRef.current = sendNotification;
  enabledRef.current = enabled;

  const doPoll = useCallback(async () => {
    if (pollingLockRef.current) return;
    pollingLockRef.current = true;
    setIsPolling(true);
    setLastError(null);

    try {
      const active = configsRef.current.filter((c) => c.enabled && c.url.trim());
      if (active.length === 0) {
        setPendingCount(0);
        setLastPollAt(new Date().toISOString());
        return;
      }

      // Find unread critical/warning alerts that haven't been pushed
      const targets = notificationsRef.current.filter((n) => {
        if (n.read) return false;
        if (n.type !== 'alert') return false;
        if (!n.severity || (n.severity !== 'critical' && n.severity !== 'warning')) return false;
        if (pushedIdsRef.current.has(n.id)) return false;
        return true;
      });

      setPendingCount(targets.length);

      if (targets.length === 0) {
        setLastPollAt(new Date().toISOString());
        return;
      }

      // Push each notification
      const results = await Promise.all(
        targets.map(async (item) => {
          try {
            const res = await sendRef.current(item);
            const success = res.some((r) => r.success);
            if (success) {
              pushedIdsRef.current.add(item.id);
            }
            return { id: item.id, success };
          } catch {
            return { id: item.id, success: false };
          }
        })
      );

      savePushedIds(pushedIdsRef.current);

      const failed = results.filter((r) => !r.success);
      if (failed.length > 0) {
        setLastError(`${failed.length}/${targets.length} 条推送失败`);
      }
    } catch (err) {
      setLastError(err instanceof Error ? err.message : '轮询失败');
    } finally {
      setLastPollAt(new Date().toISOString());
      setIsPolling(false);
      pollingLockRef.current = false;
    }
  }, []);

  // Countdown timer
  useEffect(() => {
    if (!enabledRef.current || !lastPollAt) {
      setNextPollIn(0);
      return;
    }

    const tick = () => {
      const last = new Date(lastPollAt).getTime();
      const next = last + INTERVAL_MS;
      const remaining = Math.max(0, Math.ceil((next - Date.now()) / 1000));
      setNextPollIn(remaining);

      if (remaining <= 0) {
        doPoll();
      }
    };

    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [lastPollAt, doPoll]);

  // Initial poll on mount (after a short delay)
  useEffect(() => {
    if (!enabledRef.current) return;
    const timer = setTimeout(() => {
      doPoll();
    }, 3000);
    return () => clearTimeout(timer);
  }, [doPoll]);

  return {
    isPolling,
    lastPollAt,
    nextPollIn,
    pendingCount,
    lastError,
    pushedIds: pushedIdsRef.current,
    triggerPoll: doPoll,
  };
}
