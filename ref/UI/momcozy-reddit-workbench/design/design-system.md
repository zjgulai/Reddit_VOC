# Momcozy & Reddit 舆情工作台 — 旧版设计系统参考

> **Deprecated / 非权威。** V2.0 唯一权威规范为 `../DESIGN.md`，唯一 Token 来源为
> `../src/design-tokens.json`。本文件仅用于追溯旧版设计，不得据此新增色值、圆角或组件。

---

## 设计哲学

极简、温暖、高级、专业。大量留白，精致的排版层次，克制的色彩，让内容本身说话。

**核心原则：**
1. **少即是多**：每个页面元素减少 30%
2. **留白是高级**：元素之间至少 24px 间距
3. **边框要淡**：边框颜色几乎看不见
4. **阴影要克制**：阴影几乎不可见，只是提供微妙的层次
5. **动画要优雅**：所有过渡 200-300ms，不闪不跳
6. **字体是骨架**：通过字号和字重建立层次，不依赖颜色
7. **图标要细**：使用 stroke-width 1.5 的 lucide 图标
8. **图片要精**：使用高质量插画或极简 SVG，不要占位图

---

## 颜色系统

### 品牌色
| Token | 色值 | 用途 |
|-------|------|------|
| `primary` | `#C45A6C` | 主按钮、链接、高亮 |
| `primary-hover` | `#B04D5E` | 悬停状态 |
| `primary-light` | `#FDF0F2` | 背景点缀、徽章底色 |

### 背景
| Token | 色值 | 用途 |
|-------|------|------|
| `surface` | `#FFFFFF` | 页面背景 |
| `surface-secondary` | `#FDFAF8` | 卡片背景（淡暖白） |
| `surface-tertiary` | `#FAFAFA` | Dashboard 背景、次级区域 |
| `surface-warm` | `#FFF8F5` | Hero 区域、温暖区块 |

### 文字
| Token | 色值 | 用途 |
|-------|------|------|
| `foreground` | `#1A1A1A` | 主标题、正文 |
| `foreground-secondary` | `#6B6B6B` | 次要信息 |
| `foreground-muted` | `#9A9A9A` | 辅助文字、placeholder |
| `foreground-inverse` | `#FFFFFF` | 深色背景上的文字 |

### 边框与分隔
| Token | 色值 | 用途 |
|-------|------|------|
| `border` | `#EDEDED` | 默认边框 |
| `border-hover` | `#D4D4D4` | 悬停边框 |
| `border-divider` | `#F0F0F0` | 分隔线 |

### 状态色
| Token | 色值 | 用途 |
|-------|------|------|
| `status-success` | `#2D8A5E` | 成功 |
| `status-success-bg` | `#E8F5EE` | 成功背景 |
| `status-warning` | `#D4940A` | 警告 |
| `status-warning-bg` | `#FDF6E8` | 警告背景 |
| `status-error` | `#C45A6C` | 错误（复用主色） |
| `status-error-bg` | `#FDF0F2` | 错误背景 |
| `status-info` | `#4A7FB5` | 信息 |
| `status-info-bg` | `#EEF4FA` | 信息背景 |

> **统一来源**：所有色值已收敛至 `src/design-tokens.ts` 与 `src/constants/colors.ts`，禁止在组件中写死色值。

---

## 字体系统

### 字体族
```css
font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Helvetica Neue", Arial, sans-serif;
```

### 字号层级
| 级别 | 大小 | 字重 | 行高 | 字间距 | 用途 |
|------|------|------|------|--------|------|
| Display | 40px | 600 | 1.15 | -0.02em | 首页 Hero 大标题 |
| H1 | 32px | 600 | 1.2 | -0.02em | 页面标题 |
| H2 | 28px | 600 | 1.3 | -0.015em | 区块标题 |
| H3 | 20px | 600 | 1.4 | -0.01em | 卡片标题 |
| H4 | 16px | 600 | 1.5 | 0 | 小标题 |
| Body | 15px | 400 | 1.7 | 0 | 正文 |
| Body Small | 14px | 400 | 1.6 | 0 | 次要正文 |
| Caption | 13px | 400 | 1.5 | 0 | 辅助文字、标签 |
| Tiny | 12px | 500 | 1.4 | 0.05em | 徽章、时间戳 |

> **统一来源**：字号定义已收敛至 `tailwind.config.js` 与 `src/design-tokens.ts`。

---

## 间距系统

### 页面
- 页面水平内边距：64px（桌面），24px（平板），16px（手机）
- 区块垂直间距：120px（桌面），80px（平板），60px（手机）
- 最大容器宽度：1280px

### 组件
- 卡片内边距：32px（大卡片），24px（标准），16px（紧凑）
- 卡片间距：24px
- 按钮内边距：12px 24px（标准），10px 20px（紧凑）
- 输入框内边距：12px 16px
- 组件间距：12px

> **统一来源**：间距定义已收敛至 `tailwind.config.js` 与 `src/design-tokens.ts`。

---

## 圆角系统

| 元素 | 圆角 |
|------|------|
| 卡片 | 16px |
| 按钮 | 12px |
| 输入框 | 10px |
| 标签/徽章 | 9999px（完全圆角） |
| 头像 | 50% |
| 小图标容器 | 10px |

---

## 阴影系统

| 场景 | 阴影值 |
|------|--------|
| 卡片默认 | `0 1px 3px rgba(0,0,0,0.04), 0 1px 2px rgba(0,0,0,0.02)` |
| 卡片悬停 | `0 4px 12px rgba(0,0,0,0.06), 0 2px 4px rgba(0,0,0,0.03)` |
| 下拉/弹窗 | `0 8px 24px rgba(0,0,0,0.08), 0 2px 8px rgba(0,0,0,0.04)` |
| 按钮悬停 | `0 2px 8px rgba(196,90,108,0.18)` |

---

## 组件规范

### 按钮
- **Primary**: bg `#C45A6C`, text white, radius 12px, padding 12px 24px, font-weight 500, font-size 15px
  - Hover: bg `#B04D5E`, translateY(-1px), shadow `0 2px 8px rgba(196,90,108,0.18)`
  - Active: translateY(0), shadow none
- **Secondary**: bg transparent, border 1px `#EDEDED`, text `#1A1A1A`, radius 12px
  - Hover: bg `#FAFAFA`, border `#D4D4D4`
- **Ghost**: bg transparent, text `#6B6B6B`, no border
  - Hover: bg `#F5F5F5`, text `#1A1A1A`

### 卡片
- 背景：`#FFFFFF` 或 `#FDFAF8`
- 边框：1px `#EDEDED`（可选）
- 阴影：`0 1px 3px rgba(0,0,0,0.04)`
- 圆角：16px
- Hover: shadow `0 4px 12px rgba(0,0,0,0.06)`, 过渡 300ms ease

### 输入框
- 背景：白色
- 边框：1px `#EDEDED`
- 圆角：10px
- Focus: border `#C45A6C`, ring `0 0 0 3px rgba(196,90,108,0.08)`
- Placeholder: `#9A9A9A`

### 导航栏
- 背景：白色 + backdrop-blur(12px) + 80% 透明度
- 边框底部：1px `#F0F0F0`
- 高度：68px
- Logo：纯文字，不加图标背景色块

### 标签/徽章
- 背景：`#FDF0F2`
- 文字：`#C45A6C`
- 圆角：9999px
- 内边距：6px 14px
- 字体：12px, weight 500

---

## 动画规范

- 过渡时长：200ms（快速），300ms（标准），500ms（缓慢）
- 缓动函数：`cubic-bezier(0.4, 0, 0.2, 1)`（标准）
- 页面加载：元素渐入（opacity 0→1, translateY 8px→0），stagger 100ms
- 悬停：transform + shadow 同时变化

---

## 页面结构规范

### 首页 (Landing Page) / → `src/pages/Home.tsx`
- 导航栏（透明/模糊）
- Hero：大标题 + 一句话描述 + 两个按钮 + 右侧极简插图（线条风格）
- 信任背书：一行小字 + 几个 logo 占位
- 功能：3个核心功能（不是6个），每个有大图标 + 标题 + 一行描述
- 工作原理：3步，水平排列，简洁
- 数据展示：一行数字（极简大字）
- CTA：极简，一行文字 + 一个按钮
- Footer：极简，只有 logo + 几个链接 + 版权

### Dashboard /dashboard → `src/pages/Dashboard.tsx`
- 左侧 Sidebar（固定，宽度 240px，极简图标+文字）
- 顶部：搜索框（极简，无边框或极淡边框）+ 通知 + 头像
- 数据卡片：4个，极简设计，只有数字 + 标签 + 小趋势图标
- 帖子列表：表格风格，极简边框，hover 高亮
- 右侧：洞察卡片（简洁，只有标题 + 一句话）
- 无 upgrade/套餐相关

### 登录页 /login → `src/pages/Login.tsx`
- 居中卡片: Google 登录 + 邮箱登录
- 品牌 Logo + 标语
- 注册链接

### 功能页 /features → `src/pages/Features.tsx`
- 详细功能介绍
- 每个功能的详细描述和配图

### 使用流程 /how-it-works → `src/pages/HowItWorks.tsx`
- 3步流程详细展示
- 截图/示意图

### FAQ /faq → `src/pages/FAQ.tsx`
- 常见问题手风琴
- 联系支持链接

---

## 路由结构

```
/              → Home
/dashboard     → Dashboard
/login         → Login
/features      → Features
/how-it-works  → HowItWorks
/faq           → FAQ
```

---

## 响应式断点

| 断点 | 范围 | Tailwind 前缀 |
|------|------|---------------|
| Mobile | < 640px | `sm:` |
| Tablet | 640px - 1024px | `md:` / `lg:` |
| Desktop | > 1024px | `xl:` / `2xl:` |

> 容器最大宽度：1280px（`max-w-container`）

---

## 品牌资产

- Logo: Momcozy & Reddit 舆情工作台
- 图标: Lucide React（stroke-width: 1.5）
- 无外部图片，使用 SVG 插图和图标

---

## 文件索引

| 文件 | 说明 |
|------|------|
| `src/design-tokens.ts` | 集中式 Design Tokens（TypeScript 严格类型） |
| `src/constants/colors.ts` | 颜色常量重导出（向后兼容） |
| `tailwind.config.js` | Tailwind 自定义配置（colors / fontSize / radius / shadow） |
| `src/index.css` | 全局 CSS 变量 + 组件级 utility classes |
| `tsconfig.app.json` | TypeScript 严格模式已开启 |
