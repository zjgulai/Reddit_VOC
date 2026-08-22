import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import BrandScoreCard from '../BrandScoreCard';

const dimensions = [
  { dimension: '口碑健康', score: 80, fullMark: 100 },
  { dimension: '产品体验', score: 60, fullMark: 100 },
  { dimension: '推荐信任', score: null, fullMark: 100 },
  { dimension: '风险韧性', score: 70, fullMark: 100 },
];

describe('BrandScoreCard', () => {
  it('never averages dimensions in the browser when the governed total is unavailable', () => {
    render(<BrandScoreCard overallScore={null} data={dimensions} />);

    expect(screen.getByRole('heading', { name: '品牌健康度指数' })).toBeInTheDocument();
    expect(screen.getByText('当前不可计算')).toBeInTheDocument();
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
    expect(screen.queryByText('70')).not.toBeNull();
    expect(screen.getByRole('img', { name: 'Momcozy 品牌健康四维雷达' })).toBeInTheDocument();
  });

  it('can label a governed provisional score without auto-grading it', () => {
    render(
      <BrandScoreCard
        overallScore={72.37}
        data={dimensions.map((item) => ({ ...item, score: item.score ?? 50.41 }))}
        scoreStatusLabel="真实样本计算值 · 阶段性"
      />,
    );

    expect(screen.getByTestId('brand-health-overall-score')).toHaveTextContent('72.37');
    expect(screen.getByText('真实样本计算值 · 阶段性')).toBeInTheDocument();
    expect(screen.queryByText('良好')).not.toBeInTheDocument();
  });

  it('uses red for rising and green for falling direction, independent of business meaning', () => {
    const { rerender } = render(
      <BrandScoreCard overallScore={72} trend="up" change={2.5} data={dimensions} />,
    );
    expect(screen.getByText('+2.5%').closest('span')).toHaveClass('text-status-error');

    rerender(<BrandScoreCard overallScore={69} trend="down" change={3} data={dimensions} />);
    expect(screen.getByText('-3%').closest('span')).toHaveClass('text-status-success');
  });
});
