# 功能特性交付索引（M9+ 版本化冲突仲裁与审核）

> 版本：M9+ ConflictArbiter 冲突仲裁（Issue #5 增强）| 2026-09-07
> 场景：秘书机制多 Agent 并发协作时，纯锁/版本校验不足，需"保留双方版本 + 审核仲裁"

---

## 1. 总览

在 PR #13 的 OwnershipGuard（归属声明 + 乐观版本 + 租约写锁）基础上，补上"冲突后的处置"环节：
**检测到并发修改冲突时，保留双方版本的 StateCard 快照，进行字段级差异分析，非重叠自动合并、重叠触发审核仲裁。**

| 功能编号 | 功能名称 | 状态 | 涉及文件 |
|---------|---------|------|---------|
| F-32 | ConflictArbiter 版本化冲突仲裁引擎 | ✅ 已完成 | src/hanghang/state/arbiter.py |
| F-33 | StateDiff 字段级差异分析 | ✅ 已完成 | src/hanghang/state/arbiter.py |
| F-34 | ReviewTicket 审核票据（保留双方版本） | ✅ 已完成 | src/hanghang/state/arbiter.py |
| F-35 | diffs_overlap 冲突重叠检测 | ✅ 已完成 | src/hanghang/state/arbiter.py |
| F-36 | OwnershipGuard 仲裁集成（arbitrate_conflict） | ✅ 已完成 | src/hanghang/state/ownership.py |
| F-37 | StateCard owner/version 模型扩展 | ✅ 已完成 | src/hanghang/state/models.py |
| F-38 | CLI `arb` 子命令（list/show/review/diff） | ✅ 已完成 | src/hanghang/cli/ |
| F-39 | 仲裁能力索引（M8 能力发现） | ✅ 已完成 | docs/feature-delivery-v5.md |
| F-40 | 全量回归测试 | ✅ 已完成 | tests/test_state_arbiter.py |

---

## 2. 核心机制

### 版本化保存 + 审核仲裁

```
Agent A 读 vN ──写──> vN+1 (已提交)
Agent B 读 vN ──写──> 版本冲突被拦截
                        │
                        ▼
              ConflictArbiter.capture_conflict
                        │
              ┌─────────┴──────────┐
              │                    │
        无重叠修改            有重叠修改
              │                    │
              ▼                    ▼
        auto-merge           ReviewTicket
      （双方变更保留）         （双方版本快照保留）
              │                    │
              ▼                    ▼
         写入成功            审核决策 keep_a / keep_b
```

### 为什么不只是锁/版本校验

用户洞察：**锁只能阻止"同时写"，不能阻止"基于旧理解的后续写"。**
- 即使 Agent B 重读最新版本后再次提交，仍可能按旧做法修改，语义上覆盖 Agent A 的变更。
- 正确做法：**保存双方版本 → 分析差异 → 触发审核选择保留哪个版本**。

### 与纯版本校验的区别

| 特性 | 纯版本校验(PR#13) | 版本化仲裁(本PR) |
|------|-------------------|------------------|
| 版本冲突时 | 抛异常拒绝 | 保留双方版本，生成票据 |
| B 的工作成果 | 丢失 | 保存于 card_b 快照 |
| 字段级差异分析 | 无 | StateDiff/diffs_overlap |
| 非重叠修改 | 需人工重做 | 自动合并，双方都保留 |
| 重叠修改 | 需人工重做 | 生成 ReviewTicket，审核决策 |
| 审核记录 | 无 | 票据留痕可回溯 |

---

## 3. 使用方式

### Python API（推荐，供其他模块调用）

```python
from hanghang.state import ConflictArbiter, diff_state, diffs_overlap
from hanghang.state import ReviewTicket

# 1. 创建仲裁器（完全解耦，可独立于 StateManager 使用）
arbiter = ConflictArbiter()  # data_dir 默认为 data/arbitration/

# 2. 捕获冲突
ticket = arbiter.capture_conflict(
    session_id="sess-1",
    base_card=base_card,          # 冲突前双方共同基于的版本
    conflicting_card=card_b,      # Agent B 尝试提交的版本
    current_card=card_a,          # Agent A 已提交的版本
    arbiter_name="agent_b",
    conflict_reason="两秘书同时修改任务状态",
)

# 3. 如果 ticket.status == 'pending' → 触发审核
if ticket.status == "pending":
    resolved = arbiter.review(
        ticket_id=ticket.id,
        decision="keep_a",        # or 'keep_b' / 'merge' / 'reject'
        resolver="human-reviewer",
        reason="保留 A 的修改更合理",
    )
```

### OwnershipGuard 集成

> ⚠️ **注意**：`arbitrate_conflict()` 为手动 opt-in 公共 API。版本冲突捕获
> 需要调用方在捕获到 `StateConflict` 时显式调用 `arbitrate_conflict()` 进入
> 仲裁流程。该 API 不会自动接入 guarded 写路径，调用方须自行负责在冲突处
> 转接仲裁入口。

```python
from hanghang.engine import OwnershipGuard

guard = OwnershipGuard(session_id, state_manager, secretary="agent_b")
proposed = guard.build_proposed(lambda c: c.update_task("task-1", state="done"))
ticket = guard.arbitrate_conflict(
    base_version=base_version,
    proposed_card=proposed,
    capture_base=base_snapshot,   # agent B 读取时的快照
    reason="版本冲突，需仲裁",
)
```

### CLI

```bash
# 列出待审核票据
python3 src/hanghang/cli/main.py arb list

# 查看票据详情
python3 src/hanghang/cli/main.py arb show --ticket ARB-sess-xxx-123

# 查看票据 A/B 双方字段级差异
python3 src/hanghang/cli/main.py arb diff --ticket ARB-sess-xxx-123

# 执行审核决策
python3 src/hanghang/cli/main.py arb review --ticket ARB-sess-xxx-123 \
    --decision keep_a --resolver human-1 --reason "A的修改更合理"
```

---

## 4. 能力索引

本模块作为 M9 的增强能力，可在以下层面被索引发现：

1. **Feature Delivery 索引**：本文档（docs/feature-delivery-v5.md）
2. **Python 导出**：
   - `from hanghang.state import ConflictArbiter, ReviewTicket, StateDiff`
   - `from hanghang.engine import ConflictArbiter, ReviewTicket`
   - `from hanghang.state import diff_state, diffs_overlap`
3. **CLI 入口**：`state arbiter` / `arb list/show/review`
4. **数据目录**：`data/arbitration/*.ticket.json`

---

## 5. 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| src/hanghang/state/arbiter.py | 新增 | 冲突仲裁引擎（核心 600+ 行） |
| src/hanghang/state/ownership.py | 修改 | 增加 arbitrate_conflict/build_proposed |
| src/hanghang/state/models.py | 修改 | StateCard 增 owner/version |
| src/hanghang/state/__init__.py | 修改 | 导出仲裁模块 |
| src/hanghang/engine/__init__.py | 修改 | 导出仲裁模块 |
| src/hanghang/cli/main.py | 修改 | 增 arb 子命令 |
| src/hanghang/cli/state_commands.py | 修改 | 增 arb 实现 |
| tests/test_state_arbiter.py | 新增 | 10 项仲裁测试 |
| tests/test_state_ownership.py | 新增 | 7 项归属测试 |
| docs/feature-delivery-v5.md | 新增 | 本索引文档 |
| README.md | 修改 | 用法更新 |
