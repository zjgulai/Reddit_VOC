/**
 * localStorage 版本化存储工具库
 * 所有 key 格式统一为：momcozy_{feature}_v{version}
 * 版本不匹配时自动清理旧数据并返回 fallback
 */

interface StorageWrapper<T> {
  version: number;
  data: T;
}

/** 从 localStorage 读取带版本的数据 */
export function getStorage<T>(key: string, version: number, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw) as StorageWrapper<T>;
    if (parsed.version !== version) {
      localStorage.removeItem(key);
      return fallback;
    }
    return parsed.data as T;
  } catch {
    localStorage.removeItem(key);
    return fallback;
  }
}

/** 写入带版本的 localStorage 数据 */
export function setStorage<T>(key: string, version: number, data: T): void {
  try {
    const wrapper: StorageWrapper<T> = { version, data };
    localStorage.setItem(key, JSON.stringify(wrapper));
  } catch {
    // ignore storage errors
  }
}

/** 从 localStorage 移除数据 */
export function removeStorage(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch {
    // ignore storage errors
  }
}
