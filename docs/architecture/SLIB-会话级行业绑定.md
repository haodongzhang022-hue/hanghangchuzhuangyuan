# SLIB 会话级行业绑定（Session-Level Industry Binding）

> 版本：v1.0 | 2026-09-08 | 实现：架构·开发(CodeBuddy)
> 前置设计：架构·总师（Issue #8）
> 归属模块：M4 会话编排器 · 稳定前缀约束

---

## 0. 问题定义

架构顶层方案（ARCHITECTURE.md §3.2）规定了强约束：
> **一个 session = 一个行业单元 = 一套稳定前缀。中途禁止跨行业。**

但此前该约束仅停留在架构文档的**设计原则**层面，尚未有对应的代码机制执行。实际表现：

1. **无绑定机制**：每次路由独立进行，同一会话可以从前一条"软件架构"消息漂移到下一条"健康咨询"消息。
2. **无跨行业拦截**：用户在同一会话内跨行业发问时，路由引擎会静默切换行业单元，违反"一会话一行业"。
3. **前缀不保证稳定**：会话切换行业后，前缀也跟着变，破坏缓存命中与上下文一致性。

## 1. SLIB 设计

### 1.1 核心概念

**SessionBinding（会话行业绑定）**：记录某会话（session_id）当前绑定的行业单元（unit_id）+ 行业标签（industry）+ 可选岗位（role_name）。

```
一个 session ──绑定──> 一个行业单元（unit_id）
                       └── 该单元的稳定前缀集为该会话的前缀
```

### 1.2 约束规则

| 场景 | 行为 |
|------|------|
| 会话未绑定行业 + 首次消息路由成功 | **自动绑定**到路由到的行业单元 |
| 会话已绑定行业 X + 新消息路由到 X | 正常编排（同行业岗位切换/复合均可） |
| 会话已绑定行业 X + 新消息路由到 Y（≠X） | **触发 cross_industry_handoff**：拒绝同会话切行业，建议开新 session 经交接 |
| 会话已绑定行业 X + 新消息无明确行业信号 | 尝试在 X 内识别岗位；仍无法识别则回落人工 |
| 会话无绑定 + 消息需人工 | 保持无绑定状态（不自动绑定） |

### 1.3 核心模块

| 模块 | 文件 | 职责 |
|------|------|------|
| `SessionBinding` | `src/hanghang/engine/session_binding.py` | 绑定记录数据模型 |
| `SessionBindingStore` | 同上 | 绑定持久化 CRUD（data/bindings/） |
| `SessionBoundRouter` | 同上 | 会话感知路由（SLIB 约束执行器） |

### 1.4 存储

绑定数据独立存储于 `data/bindings/<session_id>.json`，与 StateCard 分开管理。
- 每个 session 一个 JSON 文件
- 原子写（临时文件 + rename）
- 线程安全（RLock）
- session_id 校验：仅允许 `[A-Za-z0-9_-]`，防路径穿越

## 2. API 说明

### 2.1 SessionBindingStore

```python
from hanghang.engine import SessionBindingStore

store = SessionBindingStore()

# 绑定（重复绑定同行业OK，换行业抛 ValueError）
store.bind("sess-1", "dongjiagoushi", "软件研发", "architect")

# 查询
b = store.get_binding("sess-1")       # SessionBinding or None
ok = store.is_bound("sess-1")          # bool
bindings = store.list_bindings()       # List[SessionBinding]

# 解绑
store.unbind("sess-1")
```

### 2.2 SessionBoundRouter

```python
from hanghang.engine import SessionBoundRouter

router = SessionBoundRouter()

# 无 session：纯意图路由（向后兼容）
result = router.route("数据库架构设计方案")

# 有 session：会话感知路由（SLIB 执行）
result = router.route("帮我开发一个系统", session_id="sess-1")
# result["mode"] 可能是:
#   direct / composite / unit_default / manual     正常路由
#   cross_industry_handoff                          跨行业冲突 → 需开新会话
```

### 2.3 CLI

```bash
# 会话感知路由（首次自动绑定）
python3 src/hanghang/cli/main.py route "帮我做架构方案" --session "my-session"

# 跨行业检测
python3 src/hanghang/cli/main.py route "帮我制定健身计划" --session "my-session"
# => SLIB 跨行业冲突（需开新会话）

# 手动绑定会话
python3 src/hanghang/cli/main.py bind --session "my-session" --unit "dongjiagoushi"

# 查看绑定
python3 src/hanghang/cli/main.py binding --session "my-session"
python3 src/hanghang/cli/main.py bindings

# 解绑
python3 src/hanghang/cli/main.py unbind --session "my-session"
```

## 3. 设计决策

1. **绑定存储独立于 StateCard**：StateCard 侧重任务管理，SessionBinding 侧重行业约束。二者解耦，StateCard 可有可无。
2. **首次路由自动绑定**：用户发起会话的第一个消息命中某行业即自动锁定，无需手动操作。
3. **跨行业不硬拒绝、只拦截**：SLIB 不阻止用户使用新行业，而是把跨行业请求引导到新会话（经交接卡接力），保证同会话前缀稳定。
4. **向后兼容**：不带 session_id 的路由调用与原 `CompositePlanner.plan()` 行为完全一致。

## 4. 功能交付索引

| 功能编号 | 功能名称 | 状态 | 涉及文件 |
|---------|---------|------|---------|
| F-50 | SLIB SessionBinding 数据模型 | ✅ | src/hanghang/engine/session_binding.py |
| F-51 | SessionBindingStore 持久化 | ✅ | src/hanghang/engine/session_binding.py |
| F-52 | SessionBoundRouter 会话感知路由 | ✅ | src/hanghang/engine/session_binding.py |
| F-53 | CLI bind/unbind/binding/bindings | ✅ | src/hanghang/cli/main.py |
| F-54 | CLI route --session | ✅ | src/hanghang/cli/main.py |
| F-55 | SLIB 回归测试 | ✅ | tests/test_slib.py |
