import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

// Node 22+ / 25+ has an experimental globalThis.localStorage that is undefined without --localstorage-file.
// Ensure window.localStorage from jsdom is bound to globalThis.localStorage.
if (typeof window !== 'undefined' && window.localStorage) {
  const winStorage = window.localStorage;
  try {
    delete (globalThis as Record<string, unknown>).localStorage;
  } catch {
    // ignore
  }
  Object.defineProperty(globalThis, 'localStorage', {
    value: winStorage,
    configurable: true,
    writable: true,
    enumerable: true,
  });
}

afterEach(() => {
  cleanup();
});



