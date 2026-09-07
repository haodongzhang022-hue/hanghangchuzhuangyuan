# 功能特性交付索引（SLIB 会话级行业绑定）

> 版本：M4 SLIB v1.0 | 2026-09-08 | 同步人：CodeBuddy
> 场景：会话级行业绑定，确保"一个 session = 一个行业单元 = 一套稳定前缀"
> 前置：Issue #8（SLIB 会话级行业绑定为主线）

---

## 1. 总览

本阶段围绕「**SLIB 会话级行业绑定**」主线开发。此前架构顶层方案仅在设计文档中声明"一会话一行业"约束，但无对应代码执行。本期实现了会话级行业绑定的完整链路：持久化绑定、自动绑定、跨行业拦截、交接触发。

| 功能编号 | 功能名称 | 状态 | 涉及文件 |
|---------|---------|------|---------|
| F-50 | SessionBinding 数据模型 | ✅ | src/hanghang/engine/session_binding.py |
| F-51 | SessionBindingStore 持久化 CRUD | ✅ | src/hanghang/engine/session_binding.py |
| F-52 | SessionBoundRouter 会话感知路由 | ✅ | src/hanghang/engine/session_binding.py |
| F-53 | CLI bind/unbind/binding/bindings | ✅ | src/hanghang/cli/main.py |
| F-54 | CLI route --session | ✅ | src/hanghang/cli/main.py |
| F-55 | SLIB 回归测试 | ✅ | tests/test_slib.py |
| F-56 | SLIB 架构设计文档 | ✅ | docs/architecture/SLIB-会话级行业绑定.md |

---

## 2. 核心机制

### 2.1 绑定生命周期

```
消息进入
  ├─ session 无绑定
  │    ├─ 首次路由成功 → 自动绑定到路由行业
  │    └─ 路由失败(manual) → 保持无绑定
  ├─ session 已绑定 X
  │    ├─ 消息路由到 X → 正常编排
  │    ├─ 消息路由到 Y(≠X) → cross_industry_handoff（触发交接）
  │    └─ 消息无行业信号 → 在 X 内尝试岗位识别
  └─ 手动 bind/unbind 管理
```

### 2.2 SLIB 强约束执行

| 约束 | 执行方式 |
|------|---------|
| 会话不能切换行业 | `SessionBindingStore.bind` 拒绝已绑定会话换绑 |
| 跨行业需新会话 | `SessionBoundRouter` 在跨行业冲突时返回 `cross_industry_handoff` |
| 前缀稳定 | 绑定行业的稳定前缀集即为该会话的前缀（不随消息漂移） |

### 2.3 数据存储

绑定数据存于 `data/bindings/<session_id>.json`，每个会话一个文件：
```json
{
  "session_id": "demo-1",
  "unit_id": "dongjiagoushi",
  "industry": "软件研发",
  "role_name": "architect",
  "bound_at": "2026-09-08 01:49:56",
  "updated_at": "2026-09-08 01:49:56"
}
```

---

## 3. CLI 用法

```bash
# 会话感知路由（首次自动绑定）
python3 src/hanghang/cli/main.py route "帮我做架构方案" --session "my-sess"

# 跨行业检测（返回 cross_industry_handoff + 自动建交接卡）
python3 src/hanghang/cli/main.py route "帮我制定健身计划" --session "my-sess"

# 手动绑定
python3 src/hanghang/cli/main.py bind --session "my-sess" --unit "dongjiagoushi"

# 查看绑定
python3 src/hanghang/cli/main.py binding --session "my-sess"
python3 src/hanghang/cli/main.py bindings

# 解绑
python3 src/hanghang/cli/main.py unbind --session "my-sess"
```

---

## 4. 验证

- 全量 **18 个测试文件** 全部通过（17 原有 + 1 新增 SLIB 测试）
- 新增 SLIB 回归测试覆盖 20 个场景：
  - SessionBindingStore：bind/get/unbind/list/persistence/conflict/invalid_session
  - SessionBoundRouter：无 session 兼容、首次自动绑定、同行业路由、跨行业拦截、
    跨行业自动交接卡、多角色复合、手动绑定后路由、解绑后重路由、auto_bind=False
- CLI 冒烟测试通过

## 5. 文件变更清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `src/hanghang/engine/session_binding.py` | 新增 | SLIB 核心模块（数据模型/存储/路由） |
| `src/hanghang/engine/__init__.py` | 修改 | 导出 SLIB 模块 |
| `src/hanghang/cli/main.py` | 修改 | route 支持 --session；新增 bind/unbind/binding/bindings |
| `tests/test_slib.py` | 新增 | SLIB 回归测试（20 个场景） |
| `docs/architecture/SLIB-会话级行业绑定.md` | 新增 | SLIB 架构设计文档 |
| `docs/architecture/ARCHITECTURE.md` | 修改 | 里程碑 R15 |
| `README.md` | 修改 | CLI 用法/测试索引 |
| `docs/feature-delivery-v7.md` | 新增 | 本索引文档 |
