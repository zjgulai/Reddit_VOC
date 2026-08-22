import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import MetricHelpPopover from '../MetricHelpPopover';

describe('MetricHelpPopover', () => {
  it('renders definition, formula and notes with a 44px accessible trigger', () => {
    render(
      <MetricHelpPopover
        label="负面 VOC 占比"
        definition="已分类 VOC 中负向 VOC 的占比。"
        formula="negative_vocs / classified_vocs × 100%"
        notes={['未分类 VOC 不进入分母。']}
      />,
    );

    const trigger = screen.getByRole('button', { name: '负面 VOC 占比指标说明' });
    expect(trigger).toHaveClass('h-11', 'w-11');
    expect(trigger).toHaveAttribute('aria-haspopup', 'dialog');
    fireEvent.click(trigger);
    const dialog = screen.getByRole('dialog', { name: '负面 VOC 占比计算口径' });
    expect(dialog).toHaveTextContent('已分类 VOC 中负向 VOC 的占比。');
    expect(dialog).toHaveTextContent('negative_vocs / classified_vocs × 100%');
    expect(dialog).toHaveTextContent('未分类 VOC 不进入分母。');

    fireEvent.click(screen.getByRole('button', { name: '关闭负面 VOC 占比指标说明' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it('omits an unknown formula and closes on outside pointer interaction', () => {
    render(<MetricHelpPopover label="报告指标" definition="来自受治理报告产物。" />);
    fireEvent.click(screen.getByRole('button', { name: '报告指标指标说明' }));
    const dialog = screen.getByRole('dialog', { name: '报告指标计算口径' });
    expect(dialog.querySelector('code')).not.toBeInTheDocument();
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
