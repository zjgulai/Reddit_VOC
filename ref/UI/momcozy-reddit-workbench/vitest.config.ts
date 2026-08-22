import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./vitest.setup.ts'],
    // The snapshot suites load the same large governed corpus. Running test
    // files concurrently causes CPU contention and nondeterministic timeouts
    // in the release gate, while the same cases pass in isolation.
    fileParallelism: false,
    // Corpus-backed render tests can cross Vitest's 5s default during a full
    // release run even though their deterministic assertions pass in isolation.
    testTimeout: 15_000,
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html', 'lcov'],
      exclude: [
        'node_modules/',
        'src/**/*.d.ts',
        'src/data/**',
        'src/**/*.test.{ts,tsx}',
        'src/main.tsx',
        'src/App.tsx',
      ],
    },
  },
});
