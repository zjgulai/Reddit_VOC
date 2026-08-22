import { create } from 'zustand';
import type { NotificationItem } from '../types';

interface NotificationState {
  // 通知列表
  items: NotificationItem[];

  // 过滤状态
  filter: 'all' | 'alert' | 'task' | 'insight' | 'system' | 'unread';

  // 加载状态
  isLoading: boolean;

  // 时间戳
  lastUpdated: Date | null;

  // Actions
  setItems: (items: NotificationItem[]) => void;
  markRead: (id: string) => void;
  markAllRead: () => void;
  addItem: (item: NotificationItem) => void;
  removeItem: (id: string) => void;
  setFilter: (filter: NotificationState['filter']) => void;
  setLoading: (loading: boolean) => void;
  setLastUpdated: (date: Date | null) => void;

  // Getter
  filteredItems: () => NotificationItem[];
  unreadCount: () => number;
  criticalCount: () => number;
}

export const useNotificationStore = create<NotificationState>((set, get) => ({
  items: [],
  filter: 'all',
  isLoading: false,
  lastUpdated: null,

  setItems: (items) => set({ items, lastUpdated: new Date() }),
  markRead: (id) =>
    set((state) => ({
      items: state.items.map((n) => (n.id === id ? { ...n, read: true } : n)),
      lastUpdated: new Date(),
    })),
  markAllRead: () =>
    set((state) => ({
      items: state.items.map((n) => ({ ...n, read: true })),
      lastUpdated: new Date(),
    })),
  addItem: (item) =>
    set((state) => ({
      items: [item, ...state.items],
      lastUpdated: new Date(),
    })),
  removeItem: (id) =>
    set((state) => ({
      items: state.items.filter((n) => n.id !== id),
      lastUpdated: new Date(),
    })),
  setFilter: (filter) => set({ filter }),
  setLoading: (loading) => set({ isLoading: loading }),
  setLastUpdated: (date) => set({ lastUpdated: date }),

  filteredItems: () => {
    const { items, filter } = get();
    if (filter === 'all') return items;
    if (filter === 'unread') return items.filter((n) => !n.read);
    return items.filter((n) => n.type === filter);
  },

  unreadCount: () => {
    return get().items.filter((n) => !n.read).length;
  },

  criticalCount: () => {
    return get().items.filter((n) => n.type === 'alert' && n.severity === 'critical' && !n.read).length;
  },
}));
