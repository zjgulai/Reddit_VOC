import { render, screen } from '@testing-library/react';
import type { ComponentType } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import Features from '../Features';
import FAQ from '../FAQ';
import Home from '../Home';
import HowItWorks from '../HowItWorks';

function renderPage(Page: ComponentType) {
  render(
    <MemoryRouter>
      <Page />
    </MemoryRouter>,
  );
  expect(document.querySelector('[data-governance-component="data-scope-bar"]')).not.toBeInTheDocument();
  return document.body.textContent ?? '';
}

describe('public marketing claim boundaries', () => {
  it('labels the dashboard illustration as non-live and describes the static release model', () => {
    const text = renderPage(Home);

    expect(screen.getByText('功能示意 · 非实时数据')).toBeInTheDocument();
    expect(text).toContain('版本化静态快照');
    expect(text).not.toContain('每 15 分钟自动扫描新帖');
    expect(text).not.toContain('采用 AES-256 加密和 RBAC 访问控制');
    expect(text).not.toContain('一键生成专业、贴心的回复建议');
  });

  it('describes only activated features on the feature page', () => {
    const text = renderPage(Features);

    expect(text).toContain('版本化数据快照');
    expect(text).toContain('结构化 VOC 分析');
    expect(text).toContain('证据检索与回溯');
    expect(text).not.toContain('7×24 小时不间断追踪');
    expect(text).not.toContain('实时推送新帖子通知');
    expect(text).not.toContain('一键生成针对性回复内容');
  });

  it('documents real data workspaces instead of simulated operations', () => {
    const text = renderPage(HowItWorks);

    expect(text).toContain('从真实帖子、情感、严重度和互动量生成');
    expect(text).toContain('查看当前发布版本、数据范围');
    expect(text).toContain('页面不会读取、保存或测试 Webhook 配置');
    expect(text).not.toContain('实时监测新帖发布');
    expect(text).not.toContain('一键生成回复建议');
    expect(text).not.toContain('配置「Webhook 推送」');
  });

  it('answers unsupported realtime, collaboration and outbound features explicitly', () => {
    const text = renderPage(FAQ);

    expect(text).toContain('页面不承诺实时扫描或自动推送');
    expect(text).toContain('该路由已改为“数据与指标口径”');
    expect(text).toContain('当前洞察站不启用登录、子账号、RBAC');
    expect(text).toContain('因此页面不作这些承诺');
    expect(text).not.toContain('关键事件会在 5 分钟内推送');
    expect(text).not.toContain('主账号可以创建多个子账号');
    expect(text).not.toContain('我们的服务器部署在符合 SOC 2 标准的云环境中');
  });
});
