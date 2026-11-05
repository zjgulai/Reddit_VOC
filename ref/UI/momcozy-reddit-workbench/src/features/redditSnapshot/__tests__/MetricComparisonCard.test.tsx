import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { MetricComparisonCard } from '../MetricComparisonCard';

const comparisons = [
  { label: '环比' as const, display: '+12.5%', direction: 'up' as const, reasonCodes: [] },
  { label: '同比' as const, display: '—', direction: 'unavailable' as const, reasonCodes: ['缺少可比基期'] },
];

describe('MetricComparisonCard', () => {
  it('shows artifact values, unavailable dashes, and a red rising sparkline', () => {
    render(
      <MetricComparisonCard
        title="帖子观察量"
        value={42}
        explanation="当前完整自然日的去重帖子数。"
        comparisons={comparisons}
        series={[{ label: '07-13', value: 20 }, { label: '07-14', value: 30 }, { label: '07-15', value: 42 }]}
      />,
    );

    expect(screen.getByText('42')).toBeInTheDocument();
    expect(screen.getByText(/\+12\.5%/)).toHaveClass('text-status-error');
    expect(screen.getByRole('img', { name: '帖子观察量上升趋势（六期闭合期，不含当前报告期）' })).toHaveAttribute('data-trend-direction', 'up');
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('uses a green line for a falling series and a dash when fewer than two values are finite', () => {
    const { rerender } = render(
      <MetricComparisonCard
        title="负向观察量"
        value={8}
        explanation="说明"
        comparisons={comparisons}
        series={[{ label: '07-14', value: 12 }, { label: '07-15', value: 8 }]}
      />,
    );
    expect(screen.getByRole('img', { name: '负向观察量下降趋势（六期闭合期，不含当前报告期）' })).toHaveAttribute('data-trend-direction', 'down');

    rerender(
      <MetricComparisonCard
        title="负向观察量"
        value={null}
        explanation="说明"
        comparisons={comparisons}
        series={[{ label: '07-14', value: null }, { label: '07-15', value: 8 }]}
      />,
    );
    expect(screen.getByLabelText('负向观察量趋势不可用')).toHaveTextContent('—');
  });

  it('opens the focusable question help and closes it with Escape', () => {
    render(
      <MetricComparisonCard
        title="推荐表达率"
        value={null}
        explanation="只有 promoted 推荐证据和完整分母同时可用时才计算。"
        comparisons={comparisons}
        series={[]}
      />,
    );
    const trigger = screen.getByRole('button', { name: '推荐表达率指标说明' });
    fireEvent.click(trigger);
    expect(screen.getByRole('dialog', { name: '推荐表达率指标说明' })).toHaveTextContent('只有 promoted 推荐证据');
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });
});
