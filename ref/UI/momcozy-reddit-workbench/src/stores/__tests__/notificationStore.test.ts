import { describe, it, expect, beforeEach } from 'vitest';
import { useNotificationStore } from '../notificationStore';
import type { NotificationItem } from '../../types';

describe('useNotificationStore', () => {
  beforeEach(() => {
    useNotificationStore.setState({
      items: [],
      filter: 'all',
      isLoading: false,
      lastUpdated: null,
    });
  });

  it('初始状态：items 为空，filter 为 all', () => {
    const state = useNotificationStore.getState();
    expect(state.items).toEqual([]);
    expect(state.filter).toBe('all');
    expect(state.isLoading).toBe(false);
    expect(state.lastUpdated).toBeNull();
  });

  it('setItems 和 setFilter 工作正常', () => {
    const items: NotificationItem[] = [
      { id: '1', type: 'alert', title: 'Alert 1', description: 'desc', read: false, time: '2024-01-01' },
      { id: '2', type: 'task', title: 'Task 1', description: 'desc', read: true, time: '2024-01-02' },
    ];

    useNotificationStore.getState().setItems(items);
    expect(useNotificationStore.getState().items).toHaveLength(2);
    expect(useNotificationStore.getState().items[0].title).toBe('Alert 1');

    useNotificationStore.getState().setFilter('alert');
    expect(useNotificationStore.getState().filter).toBe('alert');

    useNotificationStore.getState().setFilter('unread');
    expect(useNotificationStore.getState().filter).toBe('unread');
  });

  it('markRead 标记单个通知为已读', () => {
    const items: NotificationItem[] = [
      { id: '1', type: 'alert', title: 'Alert 1', description: 'desc', read: false, time: '2024-01-01' },
      { id: '2', type: 'task', title: 'Task 1', description: 'desc', read: false, time: '2024-01-02' },
    ];
    useNotificationStore.getState().setItems(items);

    useNotificationStore.getState().markRead('1');

    const state = useNotificationStore.getState();
    expect(state.items[0].read).toBe(true);
    expect(state.items[1].read).toBe(false);
  });

  it('markAllRead 标记全部已读', () => {
    const items: NotificationItem[] = [
      { id: '1', type: 'alert', title: 'Alert 1', description: 'desc', read: false, time: '2024-01-01' },
      { id: '2', type: 'task', title: 'Task 1', description: 'desc', read: false, time: '2024-01-02' },
      { id: '3', type: 'insight', title: 'Insight 1', description: 'desc', read: false, time: '2024-01-03' },
    ];
    useNotificationStore.getState().setItems(items);

    useNotificationStore.getState().markAllRead();

    const state = useNotificationStore.getState();
    expect(state.items.every((n) => n.read)).toBe(true);
    expect(state.items[0].read).toBe(true);
    expect(state.items[1].read).toBe(true);
    expect(state.items[2].read).toBe(true);
  });

  it('addItem 添加新通知到列表顶部', () => {
    const items: NotificationItem[] = [
      { id: '1', type: 'alert', title: 'Alert 1', description: 'desc', read: false, time: '2024-01-01' },
    ];
    useNotificationStore.getState().setItems(items);

    const newItem: NotificationItem = {
      id: '2', type: 'task', title: 'New Task', description: 'desc', read: false, time: '2024-01-02',
    };
    useNotificationStore.getState().addItem(newItem);

    const state = useNotificationStore.getState();
    expect(state.items).toHaveLength(2);
    expect(state.items[0].id).toBe('2');
    expect(state.items[0].title).toBe('New Task');
    expect(state.items[1].id).toBe('1');
  });

  it('removeItem 移除通知', () => {
    const items: NotificationItem[] = [
      { id: '1', type: 'alert', title: 'Alert 1', description: 'desc', read: false, time: '2024-01-01' },
      { id: '2', type: 'task', title: 'Task 1', description: 'desc', read: false, time: '2024-01-02' },
      { id: '3', type: 'insight', title: 'Insight 1', description: 'desc', read: false, time: '2024-01-03' },
    ];
    useNotificationStore.getState().setItems(items);

    useNotificationStore.getState().removeItem('2');

    const state = useNotificationStore.getState();
    expect(state.items).toHaveLength(2);
    expect(state.items.some((n) => n.id === '2')).toBe(false);
    expect(state.items[0].id).toBe('1');
    expect(state.items[1].id).toBe('3');
  });

  it('filteredItems() 根据 filter 正确过滤', () => {
    const items: NotificationItem[] = [
      { id: '1', type: 'alert', title: 'Alert 1', description: 'desc', read: false, time: '2024-01-01' },
      { id: '2', type: 'task', title: 'Task 1', description: 'desc', read: true, time: '2024-01-02' },
      { id: '3', type: 'alert', title: 'Alert 2', description: 'desc', read: true, time: '2024-01-03' },
      { id: '4', type: 'insight', title: 'Insight 1', description: 'desc', read: false, time: '2024-01-04' },
    ];
    useNotificationStore.getState().setItems(items);

    // all filter
    useNotificationStore.getState().setFilter('all');
    expect(useNotificationStore.getState().filteredItems()).toHaveLength(4);

    // alert filter
    useNotificationStore.getState().setFilter('alert');
    expect(useNotificationStore.getState().filteredItems()).toHaveLength(2);
    expect(useNotificationStore.getState().filteredItems().every((n) => n.type === 'alert')).toBe(true);

    // task filter
    useNotificationStore.getState().setFilter('task');
    expect(useNotificationStore.getState().filteredItems()).toHaveLength(1);
    expect(useNotificationStore.getState().filteredItems()[0].type).toBe('task');

    // unread filter
    useNotificationStore.getState().setFilter('unread');
    expect(useNotificationStore.getState().filteredItems()).toHaveLength(2);
    expect(useNotificationStore.getState().filteredItems().every((n) => !n.read)).toBe(true);

    // insight filter
    useNotificationStore.getState().setFilter('insight');
    expect(useNotificationStore.getState().filteredItems()).toHaveLength(1);
    expect(useNotificationStore.getState().filteredItems()[0].type).toBe('insight');
  });

  it('unreadCount() 和 criticalCount() 返回正确数字', () => {
    const items: NotificationItem[] = [
      { id: '1', type: 'alert', title: 'Alert 1', description: 'desc', severity: 'critical', read: false, time: '2024-01-01' },
      { id: '2', type: 'alert', title: 'Alert 2', description: 'desc', severity: 'warning', read: false, time: '2024-01-02' },
      { id: '3', type: 'task', title: 'Task 1', description: 'desc', read: false, time: '2024-01-03' },
      { id: '4', type: 'alert', title: 'Alert 3', description: 'desc', severity: 'critical', read: true, time: '2024-01-04' },
      { id: '5', type: 'insight', title: 'Insight 1', description: 'desc', read: true, time: '2024-01-05' },
    ];
    useNotificationStore.getState().setItems(items);

    expect(useNotificationStore.getState().unreadCount()).toBe(3);
    expect(useNotificationStore.getState().criticalCount()).toBe(1);

    // mark a critical unread as read
    useNotificationStore.getState().markRead('1');
    expect(useNotificationStore.getState().unreadCount()).toBe(2);
    expect(useNotificationStore.getState().criticalCount()).toBe(0);

    // mark all read
    useNotificationStore.getState().markAllRead();
    expect(useNotificationStore.getState().unreadCount()).toBe(0);
    expect(useNotificationStore.getState().criticalCount()).toBe(0);
  });
});
