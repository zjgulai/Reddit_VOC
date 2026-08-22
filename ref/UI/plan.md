# Momcozy & Reddit 舆情工作台 - 复刻计划

## 项目概述
复刻 ThreadPal (https://app.threadpal.io/dashboard) 网站及其页面，应用 LUTE 主题色系，品牌改为 "Momcozy & Reddit 舆情工作台"，全面中文本地化。

## 探索结果

### ThreadPal 网站结构
- **首页** (/): 产品介绍、Features、How It Works、Pricing、FAQ、Blog
- **公开页面**: /blog, /privacy, /terms
- **Dashboard** (/dashboard): 需登录 - Reddit 舆情监测工作台
  - 核心功能: 实时监测、意图检测、线索捕获、自动工作流、AI回复建议、数据分析
- **登录/注册**: 独立的登录页面

### 颜色系统（LUTE 参考）
- **背景色**: 从渐变提取纯色 → `#FCF5F2` (暖粉米白)
- **主色/按钮**: `#C44A5E` (深玫瑰砖红)
- **文字色**: `#35141A` (深棕红)
- **辅助色**: `#F9ECEE` (浅粉), `#D75C70` (亮玫瑰红)
- **卡片背景**: `#FFFFFF` (纯白)
- **边框/分隔线**: `#E8D5D5` (淡粉灰)

### ThreadPal 原始颜色（参考）
- 背景: #F8FAFC (slate-50)
- 文字: #0F172A (slate-900)
- 按钮: 蓝紫色系

## 页面清单
1. **首页 (Landing)** - 品牌介绍、功能展示
2. **Dashboard** - 舆情工作台主界面（核心）
3. **登录/注册页** - 用户认证
4. **Features 页面** - 功能详情
5. **How It Works** - 使用流程
6. **FAQ 页面** - 常见问题

## 技术栈
- React + TypeScript + Vite
- Tailwind CSS
- React Router DOM
- Lucide React Icons

## 开发阶段

### Stage 1: 设计 & 基座搭建
- 创建 design.md 设计文档
- 初始化 Vite + React + TS 项目
- 安装 Tailwind CSS, React Router, Lucide Icons
- 配置全局主题色（LUTE 色系）
- 创建共享布局组件（Navbar, Footer, Sidebar）
- 提交基线

### Stage 2: 并行页面开发（AgentSwarm）
- Worker 1: 首页 (Landing Page) + 品牌展示
- Worker 2: Dashboard 核心工作台（搜索、帖子列表、筛选、分析面板）
- Worker 3: 登录/注册页 + Features 页面
- Worker 4: How It Works + FAQ 页面 + 全局样式微调

### Stage 3: 整合与品牌优化
- 合并所有页面
- 应用中文本地化（保留 post, reddit, subreddit）
- 移除 upgrade/套餐相关内容
- 美观优化、品牌质感提升
- 最终测试与构建

## 品牌资产
- 名称: Momcozy & Reddit 舆情工作台
- Logo: 需要生成或使用文字 Logo
- 标语: 在 Reddit 上发现你的下一个客户

## 设计原则
- 暖粉米白纯色背景（无渐变）
- 深玫瑰红作为主强调色
- 大量留白，提升品牌质感
- 圆角设计（8px-16px）
- 柔和阴影
- 中文排版优化
