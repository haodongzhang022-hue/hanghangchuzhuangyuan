# 功能特性交付索引（Web 可视化聚合面板 + M9 状态管理层）

> 版本：2026-09-07 | 同步人：CodeBuddy
> 本文档向项目协作方同步本阶段开发的功能特性与进度，涵盖：
> **Web 可视化聚合面板**（PR #9）与 **M9 状态管理层 + CLI 全链路**（PR #12）。

---

## 1. Web 可视化聚合面板（PR #9）

本阶段实现用户前期设定的「页面交互形态」，即前端只做聚合 + 可视化，作为 L2 人类端点的可视化入口。核心引擎 M1-M8 全部由 CLI 形态暴露，本期新增 **Web REST API + 单页控制台**双形态。

| 功能编号 | 功能名称 | 状态 |
|---------|---------|------|
| W-18 | Web HTTP API Server | ✅ 已完成 |
| W-19 | 单页聚合控制台页面 | ✅ 已完成 |
| W-20 | CLI serve 命令 | ✅ 已完成 |
| W-21 | Web API 自动化测试 | ✅ 已完成 |

### 功能详述

#### W-18 Web HTTP API Server

纯 Python 标准库实现（`http.server`），零新增第三方依赖。位于 `src/hanghang/web/server.py`。

提供以下 API 端点：

| 端点 | 方法 | 功能 | 对应引擎模块 |
|------|------|------|------------|
| `/api/units` | GET | 行业单元总览（全部8个单元 + 岗位 + 关键词 + 能力标签） | M2 |
| `/api/route?text=...` | GET | 意图路由识别（自然语言 → 行业/岗位） | M1/M4/M6 |
| `/api/route` | POST | 意图路由识别（JSON body） | M1/M4/M6 |
| `/api/search?kw=..&mode=..` | GET | 能力索引多维搜索（industry/capability/role/any） | M8 |
| `/api/index` | GET | 全量能力索引（能力标签 → 承接岗位） | M8 |
| `/api/metrics` | GET | 运行指标（自动成功率/复合/人工介入） | M7 |
| `/api/handoffs` | GET | 待处理交接卡 | M5 |
| `/api/prefixes` | GET | 各行业稳定前缀档案 | M3 |

#### W-19 单页聚合控制台页面

`src/hanghang/web/static/index.html` — 一个零构建依赖的单页 HTML/CSS/JS 控制台。

七个标签页：
1. **路由测试**：输入一句话意图即时路由，可视化展示行业/岗位/置信度/模式/稳定前缀
2. **行业单元**：聚合展示8个行业单元（别名/能力标签/岗位/入口）
3. **能力检索**：M8 跨行业能力多维搜索
4. **能力索引**：全量能力标签 → 承接岗位映射表
5. **运行指标**：M7 统计卡片
6. **前缀档案**：各行业稳定前缀展示
7. **交接卡**：M5 待处理交接卡

顶部实时统计卡片聚合显示行业数/累计路由/自动成功率/复合装配/交接/人工介入。

#### W-20 CLI serve 命令

新增 `hanghang serve --host --port` 子命令启动 Web 控制台。

#### W-21 Web API 自动化测试

`tests/test_web.py` — 通过本地 HTTP server 逐端点验证自动化测试用例，覆盖全部 API。

---

## 2. M9 状态管理层 + CLI 全链路（PR #12）

本阶段交付把「M9 状态管理层」从单层状态卡扩展到 **StateCard + 折叠索引 + 层级提交 + 秘书长多级树**，
并为其接通 CLI 全链路（state / tree 命令），配合**导出回归测试**（`tests/test_state_cli_e2e.py`）
确认 M9 与 CLIs 已打通、可留痕、可回溯。

| 功能编号 | 功能名称 | 状态 | 涉及文件 |
|---------|---------|------|---------|
| F-18 | StateCard 状态卡 + 任务状态机 | ✅ 已完成 | src/hanghang/state/models.py |
| F-19 | 折叠策略 FoldEngine（展开/折叠索引） | ✅ 已完成 | src/hanghang/state/fold_engine.py |
| F-20 | 层级向上提交 HierarchySubmitter | ✅ 已完成 | src/hanghang/state/hierarchy.py |
| F-21 | StateManager 状态生命周期 + JSON 落盘 | ✅ 已完成 | src/hanghang/state/manager.py |
| F-22 | 秘书长多级树 SecretaryTree（拓扑/汇总/导航） | ✅ 已完成 | src/hanghang/state/hierarchy.py |
| F-23 | CLI `state` 子命令（init/add/update/fold/submit/…） | ✅ 已完成 | src/hanghang/cli/state_commands.py |
| F-24 | CLI `tree` 子命令（init/register/link/show/rollup/…） | ✅ 已完成 | src/hanghang/cli/state_commands.py |
| F-25 | 延迟/批量落盘队列 FlushQueue/DeferredWriter | ✅ 已完成 | src/hanghang/state/persist.py |
| F-26 | M9 × CLI 全链路导出回归测试 | ✅ 已完成 | tests/test_state_cli_e2e.py |

### 功能详述

#### F-18 StateCard 状态卡 + 任务状态机

`state/models.py` 定义 `StateCard / TaskRecord / TaskState / TaskType / FoldState`：

- 每张状态卡 = 一份可恢复的**任务状态机 + 要素清单**，作为对话/任务的上下文。
- 任务状态机：`todo → in_progress → done / blocked / failed / cancelled`，`done/cancelled` 为终态，
  非终态迁移经 `TaskState.is_valid_transition` 校验，非法迁移直接拒绝。
- 任务自动编号（`<session>-NNNN`），交付任务(`deliverable`)默认展开、普通任务默认折叠。
- 秘书(坑位 role) = 该状态卡的唯一维护者/读者。

#### F-19 折叠策略 FoldEngine

解决「任务一多上下文爆炸」问题：
- **折叠索引**：把已完成/久未动的普通任务折叠为「编号 + 摘要 + content_ref」，原文不携带全量，可检索。
- 渲染层 `render_navigation`：`✅/🔄` 状态 + 进度 `n/m 完成` + 展开/折叠分区，供人类一眼全局、AI 精确检索。
- `compact_context`：生成执行 agent 视角的压缩上下文（当前执行态 + 折叠任务的编号引用）。

#### F-20 层级向上提交 HierarchySubmitter

单级/多级向上汇总：
- 只携带结构化要素（进度、关键决策、开放项），不含下层全量细节。
- 支持 `submit_up`（单级）与 `submit_chain_up`（沿树路径逐级）、断链显式跳过并提示。
- 产出含 `content_refs` 引用链，保证「上卷不丢上下文、可回溯」。

#### F-21 StateManager 状态生命周期

`state/manager.py` 提供建卡/读卡/加任务/改状态/折叠/设置上下级等完整生命周期：
- 默认落盘 `data/state/<session>.json`，write-through 即时落盘，会话间天然持久。
- session_id 白名单校验（`[A-Za-z0-9_-]`），防路径穿越。

#### F-22 秘书长多级树 SecretaryTree

超越单层状态的多级组织拓扑（秘书长 → 秘书 → 执行员）：
- 节点注册/父子 link/unlink、整树 JSON 持久化、从磁盘恢复。
- `render_tree` 树导航渲染 + `rollup` 整树逐级汇总。

#### F-23 / F-24 CLI 全链路命令

把 M9 能力接到正式 CLI 入口 `src/hanghang/cli/main.py`：
- `state init/add/show/compact/update/fold/submit/list`
- `tree init/register/link/show/rollup/submit-chain/list`

#### F-25 延迟/批量落盘队列

`state/persist.py`：把「需要落盘」的写动作统一入队，同资源多次脏写合并只写最后态；
默认 write-through（兼容既有即时落盘），规模大时可 `defer()` 切延迟批量，退出一次 flush。

#### F-26 M9 × CLI 全链路导出回归测试

`tests/test_state_cli_e2e.py`：
- **state 链路**：`init → add → update → fold → submit → show → compact → list` 全程经真实 CLI 入口调用。
- **tree 链路**：`init → register → link → show → rollup`。
- **导出回归**：校验落盘 JSON 与 CLI 视图状态一致（done 1 / in_progress 1），证明「状态流程测试绿 + 可导出」。

---

## 3. 测试覆盖

- **11 个测试文件全绿**（含新增 `test_web.py`、`test_state_cli_e2e.py`），失败 0。
- CLI 冒烟测试通过（route 正常、回落正常、serve 可启动）。
- Web 测试通过本地 HTTP server 端到端验证。
- M9 折叠 POC 量化脚本可执行并产出「压缩比/状态管理」数据。

## 4. 使用方式

```bash
# Web 可视化控制台
python3 src/hanghang/cli/main.py serve --port 8080
# 浏览器打开 http://localhost:8080/

# M9 状态管理（state / tree）
python3 src/hanghang/cli/main.py state init --session demo
python3 src/hanghang/cli/main.py tree init --tree org
```
