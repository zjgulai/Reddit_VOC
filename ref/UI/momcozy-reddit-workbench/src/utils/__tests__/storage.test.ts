import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { getStorage, setStorage, removeStorage } from '../storage';

const TEST_KEY = 'momcozy_test_storage';

describe('storage', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    localStorage.clear();
  });

  describe('getStorage', () => {
    it('returns fallback when key does not exist', () => {
      const fallback = { items: [] };
      const result = getStorage(TEST_KEY, 1, fallback);
      expect(result).toEqual(fallback);
      expect(localStorage.getItem(TEST_KEY)).toBeNull();
    });

    it('returns correct data when version matches', () => {
      const stored = { version: 2, data: { name: 'Momcozy', count: 42 } };
      localStorage.setItem(TEST_KEY, JSON.stringify(stored));
      const fallback = { name: '', count: 0 };

      const result = getStorage(TEST_KEY, 2, fallback);

      expect(result).toEqual({ name: 'Momcozy', count: 42 });
      expect(localStorage.getItem(TEST_KEY)).not.toBeNull();
    });

    it('returns fallback and removes old data when version mismatches', () => {
      const stored = { version: 1, data: 'old-value' };
      localStorage.setItem(TEST_KEY, JSON.stringify(stored));
      const fallback = 'fallback-value';

      const result = getStorage(TEST_KEY, 2, fallback);

      expect(result).toBe(fallback);
      expect(localStorage.getItem(TEST_KEY)).toBeNull();
    });

    it('returns fallback and removes key when JSON parsing fails', () => {
      localStorage.setItem(TEST_KEY, 'not-valid-json');
      const fallback = { default: true };

      const result = getStorage(TEST_KEY, 1, fallback);

      expect(result).toEqual(fallback);
      expect(localStorage.getItem(TEST_KEY)).toBeNull();
    });
  });

  describe('setStorage', () => {
    it('writes versioned data correctly', () => {
      const data = { settings: { theme: 'dark' }, enabled: true };

      setStorage(TEST_KEY, 3, data);

      const raw = localStorage.getItem(TEST_KEY);
      expect(raw).not.toBeNull();
      const parsed = JSON.parse(raw!);
      expect(parsed).toEqual({ version: 3, data });
    });
  });

  describe('removeStorage', () => {
    it('removes the key from localStorage', () => {
      localStorage.setItem(TEST_KEY, JSON.stringify({ version: 1, data: 'x' }));
      expect(localStorage.getItem(TEST_KEY)).not.toBeNull();

      removeStorage(TEST_KEY);

      expect(localStorage.getItem(TEST_KEY)).toBeNull();
    });
  });
});
