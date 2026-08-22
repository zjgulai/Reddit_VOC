import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { act } from '@testing-library/react';
import CompetitorBrandConfig from '../CompetitorBrandConfig';
import { useCompetitorStore, DEFAULT_BRANDS } from '../../stores';

describe('CompetitorBrandConfig', () => {
  beforeEach(() => {
    act(() => {
      useCompetitorStore.setState({
        brands: DEFAULT_BRANDS,
        isLoading: false,
        lastUpdated: null,
      });
    });
  });

  it('renders title and brand count', () => {
    render(<CompetitorBrandConfig />);
    expect(screen.getByText('竞品品牌配置')).toBeInTheDocument();
    expect(screen.getByText('已配置 9 / 9 个品牌')).toBeInTheDocument();
  });

  it('renders all default brands', () => {
    render(<CompetitorBrandConfig />);
    DEFAULT_BRANDS.forEach((brand) => {
      expect(screen.getByDisplayValue(brand.name)).toBeInTheDocument();
    });
  });

  it('disables add button when max brands reached', () => {
    render(<CompetitorBrandConfig />);
    const addButton = screen.getByText('添加').closest('button');
    expect(addButton).toBeDisabled();
  });

  it('removes a brand and allows adding a new one', () => {
    render(<CompetitorBrandConfig />);

    // Remove the last brand
    const removeButtons = screen.getAllByLabelText('删除');
    fireEvent.click(removeButtons[removeButtons.length - 1]);

    // Now should show 8/9
    expect(screen.getByText('已配置 8 / 9 个品牌')).toBeInTheDocument();

    // Add button should be enabled
    const addButton = screen.getByText('添加').closest('button');
    expect(addButton).not.toBeDisabled();

    // Add a new brand
    const nameInput = screen.getByPlaceholderText('输入竞品品牌名称，如 Elvie');
    fireEvent.change(nameInput, { target: { value: 'NewBrand' } });
    fireEvent.click(addButton!);

    expect(screen.getByDisplayValue('NewBrand')).toBeInTheDocument();
    expect(screen.getByText('已配置 9 / 9 个品牌')).toBeInTheDocument();
  });

  it('toggles brand enabled state', () => {
    render(<CompetitorBrandConfig />);

    const toggleButtons = screen.getAllByLabelText(/禁用|启用/);
    // First brand is enabled, so label should be "禁用"
    expect(toggleButtons[0]).toHaveAttribute('aria-label', '禁用');

    fireEvent.click(toggleButtons[0]);
    expect(toggleButtons[0]).toHaveAttribute('aria-label', '启用');
  });

  it('shows error when adding duplicate brand', () => {
    render(<CompetitorBrandConfig />);

    // Remove one to make room
    const removeButtons = screen.getAllByLabelText('删除');
    fireEvent.click(removeButtons[removeButtons.length - 1]);

    const nameInput = screen.getByPlaceholderText('输入竞品品牌名称，如 Elvie');
    fireEvent.change(nameInput, { target: { value: 'Momcozy' } });

    const addButton = screen.getByText('添加').closest('button');
    fireEvent.click(addButton!);

    expect(screen.getByText('该品牌已存在')).toBeInTheDocument();
  });

  it('shows error when name is empty', () => {
    render(<CompetitorBrandConfig />);

    // Remove one to make room
    const removeButtons = screen.getAllByLabelText('删除');
    fireEvent.click(removeButtons[removeButtons.length - 1]);

    const addButton = screen.getByText('添加').closest('button');
    fireEvent.click(addButton!);

    expect(screen.getByText('请输入品牌名称')).toBeInTheDocument();
  });

  it('adds and removes a subreddit tag', () => {
    render(<CompetitorBrandConfig />);

    const subInputs = screen.getAllByPlaceholderText('输入 subreddit 名称...');
    const firstSubInput = subInputs[0];

    fireEvent.change(firstSubInput, { target: { value: 'newsub' } });

    const addSubButtons = screen.getAllByLabelText('添加 Subreddits');
    fireEvent.click(addSubButtons[0]);

    expect(screen.getByText('newsub')).toBeInTheDocument();

    // Remove the tag
    const removeTagButton = screen.getByLabelText('删除 newsub');
    fireEvent.click(removeTagButton);

    expect(screen.queryByText('newsub')).not.toBeInTheDocument();
  });

  it('adds and removes a keyword tag', () => {
    render(<CompetitorBrandConfig />);

    const keywordInputs = screen.getAllByPlaceholderText('输入关键词...');
    const firstKeywordInput = keywordInputs[0];

    fireEvent.change(firstKeywordInput, { target: { value: 'newkeyword' } });

    const addKeywordButtons = screen.getAllByLabelText('添加 Keywords');
    fireEvent.click(addKeywordButtons[0]);

    expect(screen.getByText('newkeyword')).toBeInTheDocument();

    // Remove the tag
    const removeTagButton = screen.getByLabelText('删除 newkeyword');
    fireEvent.click(removeTagButton);

    expect(screen.queryByText('newkeyword')).not.toBeInTheDocument();
  });

  it('does not add duplicate tags', () => {
    render(<CompetitorBrandConfig />);

    const subInputs = screen.getAllByPlaceholderText('输入 subreddit 名称...');
    const firstSubInput = subInputs[0];

    fireEvent.change(firstSubInput, { target: { value: 'breastfeeding' } });

    const addSubButtons = screen.getAllByLabelText('添加 Subreddits');
    fireEvent.click(addSubButtons[0]);

    // Tag should still exist (was already there from default), input should be cleared
    expect(firstSubInput).toHaveValue('');
  });

  it('updates brand name on input change', () => {
    render(<CompetitorBrandConfig />);

    const nameInputs = screen.getAllByDisplayValue('Momcozy');
    fireEvent.change(nameInputs[0], { target: { value: 'Momcozy Pro' } });

    expect(screen.getByDisplayValue('Momcozy Pro')).toBeInTheDocument();
  });
});
