import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import SettingsPage from '../Settings';

describe('SettingsPage', () => {
  it('renders notification channel section', () => {
    render(
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>
    );
    expect(screen.getByText('通知渠道')).toBeInTheDocument();
    expect(screen.getByText('应用内通知')).toBeInTheDocument();
    expect(screen.getByText('邮件通知')).toBeInTheDocument();
    expect(screen.getByText('飞书通知')).toBeInTheDocument();
  });

  it('renders webhook configuration section', () => {
    render(
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>
    );
    expect(screen.getByText('机器人 Webhook 配置')).toBeInTheDocument();
    expect(screen.getByText('钉钉机器人')).toBeInTheDocument();
    expect(screen.getByText('飞书机器人')).toBeInTheDocument();
  });

  it('renders scheduled push configuration section', () => {
    render(
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>
    );
    expect(screen.getByText('定时推送配置')).toBeInTheDocument();
    expect(screen.getByText('日报推送')).toBeInTheDocument();
    expect(screen.getByText('周报推送')).toBeInTheDocument();
    expect(screen.getByText('月报推送')).toBeInTheDocument();
  });

  it('renders add webhook buttons', () => {
    render(
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>
    );
    expect(screen.getByText('添加钉钉机器人')).toBeInTheDocument();
    expect(screen.getByText('添加飞书机器人')).toBeInTheDocument();
  });

  it('shows test send button in webhook config', () => {
    render(
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>
    );
    // Expand the first webhook config
    const expandButtons = screen.getAllByLabelText(/展开/);
    fireEvent.click(expandButtons[0]);
    expect(screen.getByText('测试发送')).toBeInTheDocument();
  });

  it('renders competitor brand config section', () => {
    render(
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>
    );
    expect(screen.getByText('竞品品牌配置')).toBeInTheDocument();
  });

  it('does not render appearance settings', () => {
    render(
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>
    );
    expect(screen.queryByText('外观')).not.toBeInTheDocument();
    expect(screen.queryByText('主题模式')).not.toBeInTheDocument();
    expect(screen.queryByText('浅色')).not.toBeInTheDocument();
    expect(screen.queryByText('深色')).not.toBeInTheDocument();
  });

  it('does not render language settings', () => {
    render(
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>
    );
    expect(screen.queryByText('语言')).not.toBeInTheDocument();
    expect(screen.queryByText('简体中文')).not.toBeInTheDocument();
    expect(screen.queryByText('English')).not.toBeInTheDocument();
  });

  it('shows security notice about secret not being persisted', () => {
    render(
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>
    );
    expect(
      screen.getByText(/不会上传到服务器或持久化到本地存储/)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/刷新页面后需重新输入 Secret/)
    ).toBeInTheDocument();
  });
});
