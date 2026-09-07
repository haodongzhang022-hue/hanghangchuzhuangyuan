# 功能特性交付索引（M9 编排/交接进度可视化聚合）

> 版本：2026-09-08 | 同步人：CodeBuddy
> 场景：Issue #1 持续推进 —— 落地 RFC-ECO-01「生态整合接口预研」**阶段3 可视化聚合**，
> 把 M9 自动落卡的「路由编排 / 跨单元交接」StateCard 进度，在 Web L2 可视化端点聚合呈现。
> 前置：M1-M10 引擎 + Web 聚合面板已交付（PR #2/#3/#4/#6/#7/#9/#12/#18）。

---

## 1. 总览

本阶段聚焦「**可用性 / 出口复核可视化**」主线，补齐 Web 聚合面板此前缺失的 M9 状态层视图。
引擎在每次路由/交接时已自动落 StateCard（`data/state/`），但 CLI 之外的可视化端看不到进度。
本期新增只读聚合端点 + 面板「任务进度」页，让 L2 出口复核能直接看到编排/交接任务推进状态。

| 功能编号 | 功能名称 | 状态 | 涉及文件 |
|---------|---------|------|---------|
| W-46 | `GET /api/state` M9 状态卡只读聚合端点 | ✅ 已完成 | src/hanghang/web/server.py |
| W-47 | Web 面板「任务进度」标签页（路由/交接分桶 + 进度卡） | ✅ 已完成 | src/hanghang/web/static/index.html |
| W-48 | `/api/state` 自动化测试（结构/分类/落卡可追踪/只读） | ✅ 已完成 | tests/test_web.py |

---

## 2. 功能详述

### W-46 `GET /api/state`（M9 状态卡聚合，只读）

- 只读聚合 `data/state/` 下各 StateCard，**不做任何写盘**（无 GET 副作用）。
- 按 session 前缀分桶：`rt-`（路由自动落卡）→ `route`，`ho-`（交接关联卡）→ `handoff`。
- 返回三块：
  - `stats`：总卡数 / 总任务 / done / in_progress / blocked / todo / route / handoff 计数；
  - `per_unit`：按行业单元聚合的卡数 / 任务 / 完成数；
  - `cards`：每张卡的 session / 类型 / 单元 / 岗位 / 目标 / 时间 / 任务明细（含各任务 state/摘要）。

- 数据源复用模块级缓存 `StateManager`（指向 `data/state`），GET 读磁盘 JSON，天然只读。
- 每张卡目标 = 该次路由/交接意图文本，任务 = 该意图落到的各岗位/交接动作。

### W-47 Web 面板「任务进度」标签页

- 新增第 8 个标签页，聚合展示 M9 编排进度：
  - 顶部汇总：StateCard 张数（路由/交接）· 任务数 · 已完成 / 进行中 / 阻塞；
  - 每张卡渲染：类型徽标（路由/交接）+ 目标 + 单元/岗位 + 进度百分比 + 各任务状态徽标；
  - 空态友好提示（无编排记录时引导触发一次路由/交接）。

### W-48 自动化测试（test_web.py 新增 4 项）

| 用例 | 断言 |
|------|------|
| test_state_api_structure | 返回 stats/per_unit/cards，字段完整 |
| test_state_api_kind_classification | rt-→route、ho-→handoff 分类与统计一致 |
| test_state_api_post_creates_route_card | POST 复合路由落卡后 /api/state 能读到该新卡、含多岗位任务 |
| test_state_api_get_is_read_only | 多次 GET /api/state 不新增卡（只读幂等） |

---

## 3. 验证

- 全量 **17 个测试文件全部通过**（含 test_web.py 新增 4 项状态聚合用例）。
- CLI 冒烟测试通过。
- 本地 HTTP 冒烟：`GET /api/state` 返回 route/handoff 分桶统计与卡片明细正常。

## 4. 数据/接口变更

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `src/hanghang/web/server.py` | 修改 | 新增 `GET /api/state` 只读聚合端点 + 模块级 StateManager 缓存 |
| `src/hanghang/web/static/index.html` | 修改 | 新增「任务进度」标签页 + loadState 渲染 |
| `tests/test_web.py` | 修改 | 新增 4 项状态聚合 API 测试 |
| `README.md` | 修改 | Web 面板视图 + API 表补充 /api/state |
