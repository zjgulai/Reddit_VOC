# ADR-001: Reddit VOC 向通用多 Agent 架构演进与批处理流水线规范

- **状态**: Accepted (已采纳)
- **日期**: 2026-10-26
- **决策人**: VOC 核心研发团队 / 架构委员会
- **关联计划**: Batch 2 (自动化批处理、日报推送增强与工作台 Copilot 交互)

---

## 1. 背景与问题陈述 (Context & Problem Statement)

既有 Reddit VOC 系统设计定位偏向“静态数据防御与安全审计”，核心流程为单体串行管道：
1. 每日 07:00 通过爬虫拉取数据并存入 SQLite；
2. 08:00 生成固定维度的排查日报，推送到钉钉机器人；
3. 前端工作台（React）主要作为已发布静态 JSON 快照的展示器，且配置规则（如告警阈值、重点竞品）孤立存储在浏览器的 `localStorage` 中。

**面临的核心业务矛盾**：
- **数据价值利用率极低**：海外消费者在 Reddit/社媒上的真实发声只被用于“负面巡检”，未被转化为营销内容选题、硬件研发改款建议或竞品攻防情报；
- **配置与数据流撕裂**：前端配置无法下沉至后端定时任务，动态接口悬空容易触发页面报错；
- **单体架构难以扩展**：新增一个分析维度需要修改庞大的流水线脚本，缺乏解耦的业务 Agent 角色。

---

## 2. 决策驱动因素 (Decision Drivers)

1. **工业化 Agent 生命周期治理 (ALCM)**：遵循关注点分离，每个 Agent 拥有独立的领域契约、System Prompt 与评测标准。
2. **确定性与无网可用性优先 (Fail-safe & Offline Determinism)**：任何 Agent 必须具备双模执行机制（离线启发式 Fallback + 线上 LLM 结构化抽取），保障在断网、欠费或 CI 环境下永不阻塞核心流程。
3. **单源真理配置 (Single Source of Truth Configuration)**：彻底废除 `localStorage` 孤岛，统一使用版本化配置文件。
4. **渐进式平滑演进 (Non-breaking Evolution)**：新多 Agent 流程作为既有流水线的增量能力挂载，不破坏原有的 135 项核心测试与不可变数据哈希。

---

## 3. 架构决策方案 (Considered Options & Decision)

我们决定采用 **分层编排与微批流转的多 Agent 架构体系**：

```
                [ 每日采集完成: SourceBatch / SQLite ]
                                  │
                                  ▼
               ┌─────────────────────────────────────┐
               │  AgentBatchRunner (智能增量路由与调度) │
               └──────────────────┬──────────────────┘
                                  │
         ┌────────────────────────┼────────────────────────┐
         ▼                        ▼                        ▼
 ┌───────────────┐        ┌───────────────┐        ┌───────────────┐
 │ ContentScout  │        │   RndVoc      │        │CompetitorRadar│
 │ (社媒爆款选题)│        │ (研发改款建议)│        │ (竞品攻防情报)│
 └───────┬───────┘        └───────┬───────┘        └───────┬───────┘
         │                        │                        │
         └────────────────────────┼────────────────────────┘
                                  ▼
                    [ 原子化输出结构化成果集 ]
         ├── outputs/daily_content_ideas.json
         ├── outputs/daily_rnd_tickets.json
         └── outputs/daily_competitor_radar.json
                                  │
                                  ▼
                    [ 交付履约与双端消费 ]
         ├── 钉钉/飞书日报: 追加【今日爆款脚本】与【研发改款预警】
         └── 前端工作台: 详情抽屉注入 Copilot 动作按钮直接回显
```

### 3.1 核心组件划分
1. **`contracts.py` (统一数据契约)**：
   - 强类型不可变数据结构：`ContentTopicIdea`, `RndDefectFinding`, `CompetitorComparison`。
2. **Agent 核心三剑客**：
   - `ContentScoutAgent`：提炼短视频分镜脚本、黄金 3 秒 Hook、冲突矛盾；
   - `RndVocAgent`：映射到零部件（法兰/止回阀/电机），第一性原理根因分析与 CAPA 建议；
   - `CompetitorRadarAgent`：提取对标竞品（Elvie, Willow, Spectra 等）、优劣势及品牌转移意图。
3. **`AgentBatchRunner` (批处理与容错路由)**：
   - 负责根据文本特征（提及竞品、负面抱怨、高互动生活帖）进行启发式分流派发；
   - 统一管理 Token 预算，支持单条隔离与异常阻断降级。
4. **配置中心 (`config/agent_settings.json`)**：
   - 统一沉淀关注竞品列表、重点平台偏好与告警阈值。

---

## 4. 实施结果与影响 (Consequences)

### 正向影响 (Positive)
- **业务赋能直接落地**：海外社媒运营每天直接拿到分镜脚本即可拍摄；研发团队每天拿到结构化硬件改进单。
- **系统弹性极高**：通过离线启发式 Fallback，即使 DeepSeek 接口超时或配额耗尽，系统也能基于规则库输出确定性成果，不拖垮日报定时发送。
- **评测完备**：依托 Golden Dataset 建立评分基线，模型或提示词升级时能自动化回归评测。

### 潜在风险与缓解措施 (Negative & Mitigations)
- **Token 消耗增加**：
  - *缓解措施*：通过 `AgentBatchRunner` 实施严格的初筛门禁（仅将互动量前 20% 或负面 VOC 送入对应 Agent），杜绝全量低质灌入，控制单日外呼上限。
- **模型格式偶发畸变**：
  - *缓解措施*：在 `DeepSeekClient` 与各 Agent 内部实施 Pydantic / dataclass 强校验与字段安全填充兜底。
