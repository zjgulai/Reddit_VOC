# Momcozy Reddit VOC 工作台 — 执行状态交接

## 当前任务：方案B（P0 + P1 + 关键P2）

### 已确认执行项
1. **P0：清理浮窗组件**
   - 已定位：Analytics、Messages、Insights、Search 页面右上角有硬编码的独立 Bell 按钮（无实际功能，仅显示红点）
   - 待定位：左下角浮窗（需进一步检查图片确认）
   - 修复方案：将各页面的硬编码 Bell 替换为 NotificationCenter 组件，或统一移除

2. **P1：弹窗/抽屉设计**
   - 已定位以下组件的 `SectionCard` 带有 `action` 但无 `onClick`：
     - `CompetitorComparison.tsx`："查看全部" ×1，"查看详情" ×1
     - `SentimentAnalysis.tsx`："查看详情" ×1，"查看全部" ×1
     - `SubredditProfile.tsx`："查看详情" ×2
     - `InfluencerIdentification.tsx`："查看全部" ×2
     - `AudiencePersona.tsx`："查看详情" ×2
   - 待创建：通用 `ListModal` 或 `DetailDrawer` 组件

3. **P2：数据导出 + 通知中心**
   - ExportButton 已存在，支持 CSV/PDF/PPT/Word
   - 通知中心 webhook 集成需继续推进

### 下一步操作（优先级）
1. 修复所有页面的硬编码 Bell 按钮（替换为 NotificationCenter 或移除）
2. 创建通用弹窗/抽屉组件，为所有"查看全部/查看详情"添加交互
3. 推进 webhook 通知配置
4. 最终构建测试

### 技术债务记录
- 各页面 Top Bar 中的通知铃铛是重复硬编码，应提取为共享组件
- SectionCard 的 action 属性缺少弹窗交互
- 部分页面（Analytics、Messages、Insights）未使用 Dashboard 中的 NotificationCenter 集成
