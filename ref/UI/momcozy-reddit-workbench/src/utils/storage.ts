/**
 * localStorage 版本化存储工具库
 * 所有 key 格式统一为：momcozy_{feature}_v{version}
 * 版本不匹配时自动清理旧数据并返回 fallback
 */

interface StorageWrapper<T> {
  version: number;
  data: T;
}

function safeGetStorage(): Storage | null {
  if (typeof window !== 'undefined' && window.localStorage) {
    return window.localStorage;
  }
  if (typeof localStorage !== 'undefined' && localStorage) {
    return localStorage;
  }
  return null;
}

/** 从 localStorage 读取带版本的数据 */
export function getStorage<T>(key: string, version: number, fallback: T): T {
  const storage = safeGetStorage();
  if (!storage) return fallback;
  try {
    const raw = storage.getItem(key);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw) as StorageWrapper<T>;
    if (parsed.version !== version) {
      storage.removeItem(key);
      return fallback;
    }
    return parsed.data as T;
  } catch {
    try {
      storage.removeItem(key);
    } catch {
      // ignore
    }
    return fallback;
  }
}

/** 写入带版本的 localStorage 数据 */
export function setStorage<T>(key: string, version: number, data: T): void {
  const storage = safeGetStorage();
  if (!storage) return;
  try {
    const wrapper: StorageWrapper<T> = { version, data };
    storage.setItem(key, JSON.stringify(wrapper));
  } catch {
    // ignore storage errors
  }
}

/** 从 localStorage 移除数据 */
export function removeStorage(key: string): void {
  const storage = safeGetStorage();
  if (!storage) return;
  try {
    storage.removeItem(key);
  } catch {
    // ignore storage errors
  }
}

