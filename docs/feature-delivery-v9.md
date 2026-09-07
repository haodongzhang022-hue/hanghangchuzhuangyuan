# 功能特性交付索引（RFC-ECO-01 阶段4·单会话续传快照）

> 版本：2026-09-08 | 交付人：CodeBuddy
> 场景：Issue #1 持续推进 —— 落地 RFC-ECO-01「生态整合接口预研」**阶段4 的纯本仓可交付前哨**：
> 对外（外部 agent / L2 出口复核）可按 session **轮询拉取某一编排/交接会话的「待办 + 结果 + 交接关联」**，
> 用于续传或承接，而无需依赖 CLI 或对话记忆。前置：M1-M10 引擎 + Web 聚合面板 + `/api/state` 聚合已交付。

---

## 1. 总览

RFC 阶段1-3（只读聚合端点 → 可视化看板）此前已落地。阶段4（生态闭环：状态卡订阅/回传 + 接入锚点）中，
RFC 明示"首期以轮询拉取形态起步（GET /v1/state/{session}），不引入推送基础设施"。
本期把这一**轮询拉取形态**落地到可调用层：新增只读端点，将某 session 的编排快照 + 未完结待办整理为
确定性续传锚点（`resume_key`），并反查交接关联，供外部承接方续传。纯只读、零核心引擎改动、零写盘副作用。

| 功能编号 | 功能名称 | 状态 |
|---------|---------|------|
| W-49 | `GET /api/session?id=..` 单会话编排快照 + 续传锚点（只读） | ✅ 已完成 |
| W-50 | 交接会话反查 `handoff_link`（source→target / 状态） | ✅ 已完成 |
| W-51 | Web「任务进度」页单卡「续传锚点」下钻展示 | ✅ 已完成 |
| W-52 | `/api/session` 自动化测试（5 项） | ✅ 已完成 |

---

## 2. 功能详述

### W-49 `GET /api/session?id=<session_id>`

- 只读拉取 `data/state/` 下指定 StateCard；会话不存在返回 404，缺参返回 400。
- 返回五块：
  - `card`：卡概要（objective / unit_id / role_name / owner / version / 时间）；
  - `stats`：任务分桶（done/todo/in_progress/blocked/failed/cancelled）；
  - `tasks`：全量任务明细；
  - `linkage`：`upstream` + `downstream`（本卡下级 + 反向扫描"谁的 upstream==本会话"的承接卡）；
  - `resume`：**续传锚点** —— `status`（delivered/in_progress/blocked/done/empty）、
    `open_task_count`、`pending`（未完结待承接任务）、`resume_key = session@version`。

- 确定性续传语义：全部任务 done → `delivered`（无续传负担）；仍有 todo/in_progress/blocked/failed → 列出待续传清单，
  `resume_key` 作为"从该版本会话续传"的锚点（跨轮询保持一致，供外部调用方/出口复核引用）。

### W-50 交接关联反查（`handoff_link`）

- 当请求的 session 为 `ho-` 交接卡时，直接扫描交接数据目录内全部交接 JSON，
  反查 `state_card_id == session_id` 的记录，返回 `source_unit → target_unit / intent / status / card_id`，
  供续传方承接（覆盖 created/done/failed，不依赖 list_pending 的 status 过滤）。

### W-51 Web「任务进度」页单卡「续传锚点」下钻

- 每张 StateCard 新增「续传锚点」按钮：点击拉取 `/api/session?id=..` 并展开显示
  会话状态徽标、`resume_key`、交接关联、待续传任务清单（可收起）。

### W-52 自动化测试（test_web.py 新增 5 项）

| 用例 | 断言 |
|------|------|
| test_session_api_requires_id_param | 缺 id 返回 400 |
| test_session_api_404_for_unknown | 未知会话返回 404 |
| test_session_api_route_resume_snapshot | 路由卡详情 + 任务分桶 + 续传锚点（pending/resume_key/linkage） |
| test_session_api_all_done_is_delivered | 全部完成 → resume.status=delivered、pending 空 |
| test_session_api_handoff_link | 交接卡会话能反查 source→target / status |

---

## 3. 验证

- 全量 **18 个测试文件全部通过**（含 test_web.py 新增 5 项会话快照用例 + 既有 /api/state 等回归）。
- CLI 冒烟测试通过。
- 本地 HTTP 冒烟：`GET /api/session?id=rt-..` / `ho-..` 正常返回概要/统计/续传锚点/交接关联。

---

## 4. 数据/接口变更

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `src/hanghang/web/server.py` | 修改 | 新增 `GET /api/session` 端点 + `_resolve_handoff_link` 交接反查 |
| `src/hanghang/web/static/index.html` | 修改 | 「任务进度」页单卡「续传锚点」下钻 + `btn-mini`/`resume-box` 样式 |
| `tests/test_web.py` | 修改 | 新增 5 项会话快照 API 测试 |
| `README.md` | 修改 | API 表补充 `/api/session` + 功能索引 v9 |
| `docs/feature-delivery-v9.md` | 新增 | 本索引文档 |

---

## 5. 定位与后续

本期为 RFC-ECO-01 阶段4 的**轮询拉取形态**落地，属纯只读薄封装，未侵入核心引擎与既有语义。
后续可继续：阶段4的推送/Webhook 形态（需单独立项）、单元源仓统一入口规范（跨仓协作，单独立 RFC）、
多租户下状态卡读模型脱敏/权限边界。
