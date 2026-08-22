import {
  notifications,
  notificationRules,
  typeConfig,
  severityConfig,
  getPostFromNotification,
  messageSankeyNodes,
  messageSankeyLinks,
  messageWordCloudData,
} from '../data/messagesMock';
import type { Notification, NotificationRule } from '../data/messagesMock';
import api from '../lib/api';

const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true';

export async function getNotifications(): Promise<Notification[]> {
  if (USE_MOCK) {
    return [...notifications];
  }
  return api.notifications.list() as Promise<Notification[]>;
}

export async function getNotificationRules(): Promise<NotificationRule[]> {
  if (USE_MOCK) {
    return [...notificationRules];
  }
  return api.notifications.rules.list() as Promise<NotificationRule[]>;
}

export { typeConfig, severityConfig, getPostFromNotification, messageSankeyNodes, messageSankeyLinks, messageWordCloudData };
export type { Notification, NotificationRule };
