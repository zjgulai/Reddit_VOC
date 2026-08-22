import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import ExportButton from '../ExportButton';

describe('ExportButton failure semantics', () => {
  it('marks a real export failure with stable UI error severity', async () => {
    const onCustomExport = vi.fn(() => {
      throw new Error('模拟导出失败');
    });
    render(<ExportButton onCustomExport={onCustomExport} />);

    fireEvent.click(screen.getByRole('button', { name: '导出' }));
    fireEvent.click(screen.getByRole('button', { name: '导出 CSV' }));
    await waitFor(() => expect(onCustomExport).toHaveBeenCalledWith('csv'));

    fireEvent.click(screen.getByRole('button', { name: '导出' }));
    const failure = await screen.findByRole('button', { name: '导出失败' });
    expect(failure).toHaveAttribute('data-ui-severity', 'error');
    expect(failure).toHaveAttribute('title', '模拟导出失败');
  });
});
