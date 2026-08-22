# Momcozy & Reddit 舆情工作台 - 设计文档

## 视觉系统

### 颜色
- **背景**: `#FCF5F2` (暖粉米白，纯色，无渐变)
- **主色**: `#C44A5E` (深玫瑰砖红)
- **主色悬停**: `#B03A4E`
- **文字主色**: `#35141A` (深棕红)
- **文字次色**: `#7C5C62` (中灰棕)
- **文字弱化**: `#A89094` (淡灰)
- **卡片背景**: `#FFFFFF` (纯白)
- **边框/分隔**: `#E8D5D5` (淡粉灰)
- **表面色**: `#F5EBE6` (浅粉)
- **成功**: `#6B9E7C` (柔和绿)
- **警告**: `#D4A373` (暖橙)
- **错误**: `#D75C70` (亮玫瑰)

### 字体
- 主字体: `PingFang SC, Microsoft YaHei, Helvetica Neue, Arial, sans-serif`
- 标题: 字重 600-700，行高 1.2
- 正文: 字重 400，行高 1.6
- 标签/小字: 字重 500，字号 14px

### 间距
- 页面内边距: 24px (移动端 16px)
- 卡片内边距: 24px
- 卡片间距: 16px
- 组件间距: 12px
- 圆角: 卡片 16px，按钮 12px，输入框 12px，标签 9999px

### 阴影
- 卡片: `0 2px 12px rgba(53, 20, 26, 0.06)`
- 卡片悬停: `0 8px 30px rgba(53, 20, 26, 0.1)`
- 按钮悬停: `0 4px 12px rgba(196, 74, 94, 0.25)`

## 页面清单

### 1. 首页 (Landing Page) / → src/pages/Home.tsx
- 导航栏: Logo + 导航链接 + 登录/开始按钮
- Hero 区域: 大标题 + 描述 + CTA 按钮 + 插图
- 功能展示区: 6个功能卡片网格
- 工作原理: 3步流程
- FAQ 预览: 手风琴组件
- CTA 区域: 引导注册
- Footer

### 2. Dashboard /dashboard → src/pages/Dashboard.tsx
- 侧边栏: Logo + 导航菜单
- 顶部栏: 搜索 + 通知 + 用户头像
- 统计卡片: 4个 KPI 卡片
- 帖子列表: 表格/卡片视图，支持筛选
- 搜索面板: subreddit 选择 + 关键词 + 分析按钮
- 分析结果: 洞察卡片
- 无 upgrade/套餐相关

### 3. 登录页 /login → src/pages/Login.tsx
- 居中卡片: Google 登录 + 邮箱登录
- 品牌 Logo + 标语
- 注册链接

### 4. 功能页 /features → src/pages/Features.tsx
- 详细功能介绍
- 每个功能的详细描述和配图

### 5. 使用流程 /how-it-works → src/pages/HowItWorks.tsx
- 3步流程详细展示
- 截图/示意图

### 6. FAQ /faq → src/pages/FAQ.tsx
- 常见问题手风琴
- 联系支持链接

## 组件清单

### 共享组件
- Navbar (导航栏)
- Footer (页脚)
- Sidebar (侧边栏 - Dashboard 用)
- Card (通用卡片)
- Button (按钮)
- Input (输入框)
- Badge (标签)
- Accordion (手风琴 - FAQ 用)

### 页面组件
- HeroSection (首页 Hero)
- FeatureCard (功能卡片)
- StatCard (统计卡片)
- PostCard (帖子卡片)
- InsightCard (洞察卡片)
- SearchPanel (搜索面板)

## 路由结构
```
/              → Home
/dashboard     → Dashboard
/login         → Login
/features      → Features
/how-it-works  → HowItWorks
/faq           → FAQ
```

## 响应式断点
- Mobile: < 640px
- Tablet: 640px - 1024px
- Desktop: > 1024px

## 品牌资产
- Logo: Momcozy & Reddit 舆情工作台
- 图标: Lucide React
- 无外部图片，使用 SVG 插图和图标
