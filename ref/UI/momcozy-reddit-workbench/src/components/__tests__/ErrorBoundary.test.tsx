import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ErrorBoundary from '../ErrorBoundary';

function BrokenChild(): never {
  throw new Error('snapshot manifest hash mismatch');
}

describe('ErrorBoundary failure fallback', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('stays usable without Router context and preserves the original error', () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);

    expect(() => {
      render(
        <ErrorBoundary>
          <BrokenChild />
        </ErrorBoundary>,
      );
    }).not.toThrow();

    const failureRoot = screen.getByText('页面出错了').closest('[data-ui-severity="error"]');
    expect(failureRoot).toBeInTheDocument();
    expect(screen.getByText('snapshot manifest hash mismatch')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '返回首页' })).toHaveAttribute('href', '/');
  });
});
