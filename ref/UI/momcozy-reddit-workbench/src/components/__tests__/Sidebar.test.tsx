import { act, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Sidebar from '../Sidebar';

type MediaListener = (event: MediaQueryListEvent) => void;

function installMatchMedia(initialMatches: boolean) {
  let matches = initialMatches;
  const listeners = new Set<MediaListener>();
  const mediaQuery = {
    get matches() {
      return matches;
    },
    media: '(max-width: 639px)',
    onchange: null,
    addEventListener: (_type: string, listener: MediaListener) => listeners.add(listener),
    removeEventListener: (_type: string, listener: MediaListener) => listeners.delete(listener),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  } as unknown as MediaQueryList;

  vi.stubGlobal('matchMedia', vi.fn(() => mediaQuery));

  return (nextMatches: boolean) => {
    matches = nextMatches;
    const event = { matches, media: mediaQuery.media } as MediaQueryListEvent;
    act(() => listeners.forEach((listener) => listener(event)));
  };
}

describe('Sidebar responsive state', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.unstubAllGlobals();
  });

  it('forces the icon-only 64px sidebar on mobile without overwriting the desktop preference', () => {
    localStorage.setItem('sidebar-collapsed', JSON.stringify({ version: 1, data: false }));
    installMatchMedia(true);

    render(
      <MemoryRouter initialEntries={['/cases']}>
        <Sidebar />
      </MemoryRouter>,
    );

    const sidebar = screen.getByRole('complementary');
    expect(sidebar).toHaveClass('w-[64px]');
    expect(screen.queryByRole('button', { name: '展开侧边栏' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: '案例广场' })).toBeInTheDocument();
    expect(JSON.parse(localStorage.getItem('sidebar-collapsed')!)).toEqual({ version: 1, data: false });
  });

  it('reacts to viewport changes while preserving the expanded desktop layout', () => {
    const setMobile = installMatchMedia(false);

    render(
      <MemoryRouter initialEntries={['/dashboard']}>
        <Sidebar />
      </MemoryRouter>,
    );

    const sidebar = screen.getByRole('complementary');
    expect(sidebar).toHaveClass('w-[240px]');

    setMobile(true);
    expect(sidebar).toHaveClass('w-[64px]');

    setMobile(false);
    expect(sidebar).toHaveClass('w-[240px]');
  });
});
