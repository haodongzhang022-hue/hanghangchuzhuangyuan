# RFC · 生态整合接口预研（agent 协作 / API 编排 / 前端聚合可视化）

> 类型：架构演进 RFC（预研，非落地实现）
> 编号：RFC-ECO-01
> 责任人：架构·总师（本 RFC 由编排角色代拟草稿，待总师评审放行）
> 状态：**草案** · 依赖：T1（M9×CLI 全链路）✅ 已闭合
> 关联：M8 `capability_index()` 导出、M5 交接卡、M9 状态卡/树、CLI `index` 命令

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

## 4. 分层演进路径（建议）

```
阶段1(纯只读暴露)：/v1/index、/v1/metrics、/v1/state 只读查询 —— 零引擎改动
阶段2(触发端点)：   /v1/route 薄适配层 + state_card 自动落盘
阶段3(可视化)：     只读聚合端点 → 看板
阶段4(生态闭环)：   交接卡订阅/回传 + 外部 agent 接入锚点统一
```

- **阶段1–3 不侵入核心引擎**，风险低，可作为下一开发迭代候选。
- 阶段4 需明确「单元源仓统一入口规范」，牵涉跨仓协作，单独立 RFC。

## 5. 开放问题 / 待总师定夺

1. API 载体：HTTP 服务（FastAPI）vs 函数式/CLI 聚合端点？首期建议 CLI 聚合 + 可选薄 HTTP。
2. `entry_ref` 语义是否需扩展为「API 基址 + 鉴权」以支撑形态B 真实跨仓调用？
3. 可视化前端是否在本仓（集中）开发，还是独立仓？——遵循用户「非重点尽量集中本仓」口径。
4. 状态卡对外的读模型是否需脱敏/权限边界（多租户场景）。

## 6. 结论

- 编排能力（M1–M9）已为生态整合备好**结构化数据契约**。
- T2 预研表明：走「只读聚合端点 → 触发端点 → 可视化 → 生态协作」的**分层轻量**路径
  风险最低，前两层几乎零核心引擎改动。
- 本 RFC 为**草案**，待架构·总师评审放行后落入 docs/architecture 定稿，再行排期落地。
