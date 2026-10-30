# RFC · 生态整合接口预研（agent 协作 / API 编排 / 前端聚合可视化）

> 类型：架构演进 RFC（预研定稿）
> 编号：RFC-ECO-01
> 责任人：架构·总师（草稿由编排角色代拟，经架构·总师评审放行定稿）
> 状态：**已评审定稿（架构·总师 Issue #14）** · 依赖：T1（M9×CLI 全链路）✅ 已闭合
> 评审：Issue #14 架构·总师放行；T2 阶段定稿由 CodeBuddy 依总师决策整理
> 关联：M8 `capability_index()` 导出、M5 交接卡、M9 状态卡/树、CLI `index` 命令、
>       Web `/api/*` 只读聚合端点（阶段1–4 落地产物）
> 落地产物交付索引见 §7 与 `docs/feature-delivery-v3/v8/v10`。

---

## 1. 背景与动机

当前通用能力层已完成 M1–M9，具备「一句话意图 → 自动识别行业/岗位 → 路由/交接/复合装配
→ 状态留痕」的核心编排闭环。**最后一块拼图**是：

> 让已编排好的「能力足够高」的路由结果，能被**外部生态消费**：
> ① 别的 agent / 自动化流水线按 API 触发并获取结构化编排结果；
> ② 前端/可视化面板把多行业能力聚合展示。

T2 目标是**预研**这些整合接口的形态，形成 RFC 供后续落地，不阻塞也不替代 T1/T3。

## 2. 现状可复用接口（预研基点）

| 能力 | 现有接口 | 说明 |
|------|---------|------|
| 能力索引导出 | `Registry.capability_index()` / CLI `index` | 输出 `tag_to_roles / entry_ref / roles` 全量映射 |
| 意图路由 | `IntentRouter.route(text)` | 返回 `unit_id / industry / roles / confidence / needs_manual` |
| 会话编排 | `CompositePlanner.plan_from_result()` | 输出 `mode / execution_order / session_prefix_set / handoff_card_id` |
| 交接 | `HandoffBus.create_handoff()` | 跨单元接力卡 |
| 状态 | `StateManager` / `SecretaryTree` | 状态卡 + 多级树 + 层级提交 |

> 结论：编排层所需的数据契约**基本齐备**，缺的是「对外稳定暴露 + 聚合呈现」这层薄封装。

## 3. 整合形态预研

### 3.1 形态A：API 编排端点（结构化 JSON 触发）

把 `route + plan_from_result + 状态卡创建` 收敛为一个无状态 HTTP/函数端点：

```
POST /v1/route
{ "text": "既要架构设计又要编码，还要做产品规划" }

→ 200
{ "mode": "composite",
  "unit_id": "dongjiagoushi",
  "industry": "软件研发",
  "roles": ["product","architect","developer"],
  "execution_order": ["product","architect","developer"],
  "session_prefix_set": ["[产品]","[架构]","[开发]"],
  "state_card_id": "SC-xxx" }      # 自动落一张状态卡，可续传
```

- **可行性**：引擎逻辑已收敛于 `plan_from_result`（避免二次 route），仅需薄适配层封装。
- **返回稳定前缀集 / state_card_id**：供调用方在外部维持会话上下文（延续 M3/M9 约束）。
- **交接跨单元**：`mode=cross_unit_handoff` 时返回 `handoff_card_id`，调用方凭卡续传。

### 3.2 形态B：agent 协作协议（跨单元接力/回传）

在 M5 交接卡 + M9 层级提交之上定义**外部 agent 协作协议**：

- 每个行业单元的 `entry_ref`（如 `dongjiagoushi` 的源仓）作为该单元的「能力接入锚点」。
- 交接卡 `intent/context` 即最小协作契约：`source_unit → target_unit → intent → context`，
  已可在 CLI `handoff`/`cross-unit` 生成。
- M9 状态卡/树作**回传层**：子任务完成 → `submit` 向上汇总 → 根卡呈现给发起方。

**要预研的点**：外部 agent 如何「订阅」/「拉取」某状态卡的待办与结果
（`GET /v1/state/{session}` 或 Webhook 回调）。本 RFC 建议首期以**轮询拉取**形态起步，不引入推送基础设施。

### 3.3 形态C：前端聚合可视化

把 M8 能力索引 + M7 指标 + M9 状态树渲染成**聚合看板**：

| 面板 | 数据源 | 已有 |
|------|--------|------|
| 跨行业能力总览 | `capability_index()` / `index` CLI | ✅ |
| 行业单元路由命中/介入率 | `MetricsCollector` | ✅ |
| 复合装配/交接关系图 | `plan` + `handoff_card` | 部分 |
| 状态/任务进度树 | `SecretaryTree.render_tree()` / `tree show` | ✅ |

- 已有一棵只读数据源（CLI/引擎层），前端只需一个只读 JSON 聚合端点，无需改核心引擎。
- 复用 `tree show` 的树导航渲染语义 → 前端可直接消费其结构化数据。

## 4. 分层演进路径（定稿）

```
阶段1(纯只读暴露)：/v1/index、/v1/metrics、/v1/state 只读查询 —— 零引擎改动   ✅ 已落地
阶段2(触发端点)：   /v1/route 薄适配层 + state_card 自动落盘                    ✅ 已落地
阶段3(可视化)：     只读聚合端点 → 看板                                        ✅ 已落地
阶段4(生态闭环)：   状态卡轮询拉取(首期) + 外部 agent 接入锚点统一              🟡 轮询拉取已落地；推送/接入锚点统一另立 RFC
```

- **阶段1–4（本仓可交付前哨）不侵入核心引擎**，风险低，已按序落地（见 §7 落地产物索引）。
- 阶段4 的**推送/Webhook 形态**与**「单元源仓统一入口规范」**（跨仓协作、牵涉鉴权）需单独立 RFC，
  不在本 RFC 承诺范围内。

## 5. 开放问题 · 决议摘要（已定稿）

> 以下四条在架构·总师评审（Issue #14）后定稿，作为演进与排期依据。

1. **API 载体（HTTP vs 函数式/CLI）** → **本仓集中，CLI + 薄 HTTP 双形态**。
   采用纯 Python 标准库 `http.server` 实现 Web REST（`/api/*`）+ 单页控制台，
   **零新增第三方依赖**，避免引入 FastAPI；CLI（`route/index/...`）保持函数式聚合形态并存。
2. **`entry_ref` 是否扩展为「API 基址 + 鉴权」** → **首期不做跨仓真实调用**。
   保持 `entry_ref` 作为该单元的「能力接入锚点」（源仓标识）；跨仓统一入口 + 鉴权规范
   牵涉多仓协作，**单独立 RFC**，不在本期落地。
3. **可视化前端集中本仓还是独立仓** → **集中本仓**（遵循用户「非重点尽量集中本仓」口径）。
   已落地 Web 聚合面板（`src/hanghang/web/static/`），前端只做「聚合 + 可视化」。
4. **状态卡对外读模型脱敏/权限边界（多租户）** → **本期单租户/本地化，暂不引入多租户鉴权**。
   对外仅暴露只读聚合/轮询拉取端点（`/api/state`、`/api/session`），**无写盘副作用、无推送基础设施**；
   多租户脱敏与权限边界留待后续单独立项。

## 6. 结论

- 编排能力（M1–M10）已为生态整合备好**结构化数据契约**。
- 走「只读聚合端点 → 触发端点 → 可视化 → 生态协作」的**分层轻量**路径风险最低，
  阶段1–4（本仓可交付前哨）已全部落地，核心引擎零侵入。
- 本 RFC 经架构·总师评审放行，自 **Issue #14** 起为**已评审定稿**，
  作为后续生态整合迭代的基线；未决跨仓项单独立 RFC。

## 7. 阶段1–4 落地产物索引

> 阶段1–4 的**纯本仓可交付前哨**已随各期功能交付落地，端点/文档对应关系如下
> （交付索引见对应 feature-delivery 文档）。

| 阶段 | 落地产物（Web endpoint / 能力） | 交付文档 |
|------|--------------------------------|---------|
| 阶段1 · 纯只读暴露 | `GET /api/units`、`GET /api/search`、`GET /api/index`、`GET /api/metrics`、`GET /api/prefixes`、`GET /api/handoffs` | `docs/feature-delivery-v3.md`（PR #9） |
| 阶段1 · M9 状态只读聚合 | `GET /api/state`（M9 编排/交接状态卡聚合，只读） | `docs/feature-delivery-v8.md`（W-46~W-48） |
| 阶段2 · 触发端点 | `GET/POST /api/route`（意图路由 + 自动落 StateCard + 记指标） | `docs/feature-delivery-v3.md`（PR #9） |
| 阶段3 · 可视化 | Web 单页聚合控制台 `src/hanghang/web/static/index.html` +「任务进度」页 | `docs/feature-delivery-v3.md`、`docs/feature-delivery-v8.md`（W-47） |
| 阶段4 · 轮询拉取 | `GET /api/session?id=..`（单会话编排快照 + 续传锚点 resume_key） | `docs/feature-delivery-v10.md`（W-49~W-52） |

> **未落地区块（留待后续单独立 RFC）**：阶段4 推送/Webhook 形态、单元源仓统一入口（API 基址+鉴权）。

## 8. 演进优先级（定稿）

> 承接开放问题决议，对后续生态整合迭代按价值/风险分级（P0 已闭环/当轮必达；P1 高优先；P2 顺延）：

| 优先级 | 演进项 | 说明 / 状态 |
|--------|--------|------------|
| **P0** | 本仓只读聚合 + 触发端点 + 可视化看板 + 状态轮询拉取 | 阶段1–4 纯本仓前哨，**已落地闭环**（§7） |
| **P0** | 本 RFC 文档定稿与落地产物索引收敛 | 本 Issue #14 T2，**已完成**（§7/§5） |
| **P1** | 生态整合 CLI 侧可用性补齐（context 装配子命令等） | 与 M10 联动，随本 PR 落地（Issue #14 T1） |
| **P1** | 阶段4 推送/Webhook 形态 | 需引入订阅基础设施，单独立 RFC 排期 |
| **P2** | 单元源仓统一入口（API 基址 + 鉴权）跨仓协作 | 牵涉多仓规范，单独立 RFC，本期不承诺 |
| **P2** | 状态卡对外读模型多租户脱敏/权限边界 | 本期单租户/本地化，待业务出现多租户诉求再立 RFC |
