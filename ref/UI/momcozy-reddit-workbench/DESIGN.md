# Momcozy Reddit VOC Design System — Warm Intelligence

> Status: authoritative
> Version: 2.0
> Updated: 2026-07-22
> Token source: `src/design-tokens.json`

本文件是洞察站唯一权威设计规范。颜色、字号、圆角、阴影和图表色必须从
`src/design-tokens.json` 派生；`design/design-system.md` 仅保留为历史参考。

## 1. Visual theme

**Momcozy Warm Intelligence**：温暖但不幼态，专业但不冷硬，数据密集但保持平静。

- 暖米色画布承载白色内容面；
- 暖珊瑚用于 Momcozy 品牌、关键选中态和主要行动；
- 数据、结论和 Reddit 原始证据是视觉主角；
- 一屏最多一个暖色强调面，不连续使用大面积渐变；
- 页面顺序服务“判断 → 原因 → 行动 → 证据”。

## 2. Color roles

- `coral-500`：品牌资产、图表、浅色块，不承载普通白字小按钮；
- `coral-700`：按钮、链接、Focus 和可访问交互文字；
- `competitor`：所有竞品的低饱和冷灰蓝对照；
- `negative`、`positive`、`warning`、`neutral`：固定业务语义，不随数组顺序改变；
- `canvas-warm`、`surface`、`surface-soft`：建立层级，不依赖大阴影。

Momcozy、竞品、正面、负面和中性在所有页面、截图和导出中必须保持同一颜色角色。

## 3. Typography

- 字体：系统无衬线栈，保证中文与英文一致；
- 层级：Display 32、Page 24、Section 20、Card 16、Body 14–15、Caption 12–13；
- KPI 使用 tabular numbers；数字、单位、比较值分层；
- 标题不依赖全粗体建立层级，常规最高字重为 600；
- 工程 release、SHA 和口径元数据使用等宽字体或紧凑 Caption。

## 4. Components and states

- `surface-card` / `.card`：静态数据面，无 hover 位移；
- `interactive-card`：明确可点击，hover 使用边框或底色变化，不上浮；
- `overlay`：Drawer、Popover、Modal，可使用阴影；
- Primary button 使用深珊瑚交互色；浅珊瑚只作品牌与图表色；
- 指标帮助统一为一个组件，实际触控区至少 44px，支持 Tab、Enter/Space、Esc 和点击外部关闭；
- 每个交互必须定义 default、hover、focus、pressed、disabled；
- `fresh`、`partial`、`stale`、`failed` 必须同时有文字，不只依赖颜色。

## 5. Layout

- 间距：4 / 8 / 12 / 16 / 24 / 32 / 48；
- 内容最大宽度：1440px，超宽屏居中；
- 标准卡片圆角 12px，强调面板 16px，Badge 全圆；
- 桌面保留侧栏；移动端使用“核心五项 + 更多”覆盖全部模块；
- 概览首屏固定为新鲜度、时间窗口、四 KPI、健康度、双轴趋势、决策入口和行动；
- 日报、周报、月报拥有不同信息架构，不共用一套内容仅换标题。

## 6. Elevation and motion

- 静态卡片默认无阴影，以画布、白面和 hairline 建立层级；
- 只有 overlay 使用显著阴影；
- 动画用于状态变化，不用于制造装饰；
- `prefers-reduced-motion` 和报告截图模式关闭全部非必要动画；
- 禁止卡片 hover 上浮和页面加载的大面积 stagger。

## 7. Charts and evidence

- 图表先写清业务问题，再选择图形；
- Momcozy 固定暖珊瑚，竞品固定冷灰蓝；
- 数量与比例允许双轴，但必须显示单位、分母和口径；
- 上升红、下降绿只表达趋势方向；业务好坏必须由指标语义说明；
- 图例、公式 `?`、数据窗口和证据下钻不可缺失；
- 真实 0、缺失、不可计算和未闭合周期不得混淆；
- 案例方法必须标注“方法参照，不是本期数据”。

## 8. Do / Don't

### Do

- 使用语义 Token；
- 保留 Momcozy 暖色骨架和当前真实数据故事线；
- 让所有关键判断可下钻到帖子和评论证据；
- 常驻展示 `data_as_of`、run、center release、projection release 和 coverage；
- 让筛选、Tab 和时间窗口可通过 URL 恢复。

### Don't

- 不在组件中新增未经登记的业务色、圆角和阴影；
- 不用随机图表色表达品牌或情感；
- 不让静态卡片假装可点击；
- 不用渐变、毛玻璃和大阴影制造“高级感”；
- 不用旧截图或旧 release 冒充本期报告；
- 不恢复演示数据模型替代 V3 真实报告。

## 9. Responsive and capture mode

- 1440px：完整经营工作台；
- 1024px：收敛次级解释，保留核心图表和证据入口；
- 390px：单列阅读，筛选使用 Bottom Sheet，所有生产模块可达；
- `capture=poster`：隐藏导航、刷新、导出、Tooltip 和动画；
- 报告截图只截取 `data-report-capture-root`，必须等待 `data-report-ready=true`；
- 截图、页面、导出和钉钉消息必须绑定同一 data release。

## 10. Implementation rules

1. 修改视觉前先检查 `src/design-tokens.json` 是否已有对应角色；
2. Tailwind、TypeScript、CSS 变量、图表和导出只引用 Token；
3. 新组件必须有键盘、移动端、空态和截图模式测试；
4. 新图表必须有指标口径、单位、空值规则和证据下钻；
5. 变更完成后执行 test、lint、build 和视觉回归；
6. 任何偏离本规范的临时实现不得进入可发布候选。
