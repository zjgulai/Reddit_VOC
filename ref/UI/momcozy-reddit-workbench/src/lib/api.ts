/** API 客户端封装 - 预留后端接口层 */

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1';

interface RequestOptions extends RequestInit {
  params?: Record<string, string | number | boolean | undefined>;
  timeout?: number;
}

class ApiError extends Error {
  status: number;
  code: string;
  constructor(message: string, status: number, code: string) {
    super(message);
    this.status = status;
    this.code = code;
    this.name = 'ApiError';
  }
}

async function buildUrl(path: string, params?: Record<string, string | number | boolean | undefined>): Promise<string> {
  const url = new URL(path, API_BASE_URL);
  if (params) {
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null) {
        url.searchParams.set(key, String(value));
      }
    });
  }
  return url.toString();
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { params, timeout = 30000, ...fetchOptions } = options;
  const url = await buildUrl(path, params);

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeout);

  try {
    const response = await fetch(url, {
      ...fetchOptions,
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        ...fetchOptions.headers,
      },
      signal: controller.signal,
    });

    clearTimeout(timeoutId);

    if (!response.ok) {
      const errorBody = await response.json().catch(() => ({ message: 'Unknown error' }));
      throw new ApiError(
        errorBody.message || `HTTP ${response.status}`,
        response.status,
        errorBody.code || 'UNKNOWN_ERROR'
      );
    }

    const data = await response.json();
    return data;
  } catch (error) {
    clearTimeout(timeoutId);
    if (error instanceof ApiError) throw error;
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new ApiError('Request timeout', 408, 'TIMEOUT');
    }
    throw new ApiError(error instanceof Error ? error.message : 'Network error', 0, 'NETWORK_ERROR');
  }
}

// ========== API 接口定义（预留）==========
export const api = {
  // 报告
  reports: {
    getDaily: () => request('/reports/daily'),
    getWeekly: () => request('/reports/weekly'),
    getMonthly: () => request('/reports/monthly'),
  },

  // 通知
  notifications: {
    list: (params?: { page?: number; pageSize?: number; type?: string; read?: boolean }) =>
      request('/notifications', { params }),
    markRead: (id: string) => request(`/notifications/${id}/read`, { method: 'POST' }),
    markAllRead: () => request('/notifications/read-all', { method: 'POST' }),
    rules: {
      list: () => request('/notification-rules'),
      update: (id: string, data: unknown) => request(`/notification-rules/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
    },
  },

  // 搜索
  search: {
    execute: (configId: string, params?: { page?: number; pageSize?: number }) =>
      request(`/search/${configId}`, { params }),
    configs: {
      list: () => request('/search-configs'),
      create: (data: unknown) => request('/search-configs', { method: 'POST', body: JSON.stringify(data) }),
      update: (id: string, data: unknown) => request(`/search-configs/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
      delete: (id: string) => request(`/search-configs/${id}`, { method: 'DELETE' }),
    },
  },

  // 分析
  analytics: {
    overview: (params?: { startDate?: string; endDate?: string }) =>
      request('/analytics/overview', { params }),
    sentiment: (params?: { subreddit?: string; period?: string }) =>
      request('/analytics/sentiment', { params }),
    competitors: () => request('/analytics/competitors'),
    topics: () => request('/analytics/topics'),
  },

  // 洞察
  insights: {
    list: (params?: { page?: number; pageSize?: number; type?: string; status?: string }) =>
      request('/insights', { params }),
    updateStatus: (id: string, status: string) =>
      request(`/insights/${id}/status`, { method: 'PATCH', body: JSON.stringify({ status }) }),
  },

  // 用户
  user: {
    profile: () => request('/user/profile'),
    updateSettings: (data: unknown) => request('/user/settings', { method: 'PATCH', body: JSON.stringify(data) }),
  },
};

export { ApiError };
export default api;
