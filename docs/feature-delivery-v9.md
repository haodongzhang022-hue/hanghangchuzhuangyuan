# 功能特性交付索引（ContentArchive 原文归档检索层）

> 版本：M9+ ContentArchive v1.0 | 2026-09-08 | 同步人：CodeBuddy
> 场景：补齐秘书机制"折叠后原文不丢、编号可找回"的关键缺口
> 前置：PR #15（M9+ 版本化冲突仲裁与审核）已合入 main

---

## 1. 总览

Issue #5 秘书机制的核心承诺之一是：**原文不是丢弃，而是保留 + 编号索引可检索**。
此前 `FoldEngine.fold_content` 仅为每个折叠任务生成一个 `content_ref` **编号标记**
（如 `sess-seg001`），并未真正持久化对应原文全文 —— 折叠后无法按 content_ref 找回原文。

本阶段新增 **ContentArchive 原文归档检索层**，把"编号即索引、可寻回原文"落实为真实能力。

| 功能编号 | 功能名称 | 状态 | 涉及文件 |
|---------|---------|------|---------|
| F-57 | ContentArchive 原文归档存储层 | ✅ | src/hanghang/state/content_archive.py |
| F-58 | FoldEngine.fold_content 自动归档原文 | ✅ | src/hanghang/state/fold_engine.py |
| F-59 | FoldEngine.retrieve_original 按引用取回原文 | ✅ | src/hanghang/state/fold_engine.py |
| F-60 | search_tasks(include_original=True) 命中返回原文 | ✅ | src/hanghang/state/fold_engine.py |
| F-61 | CLI state archive/retrieve/refs/full | ✅ | src/hanghang/cli/ |
| F-62 | ContentArchive 路径穿越加固 + 原子写 | ✅ | src/hanghang/state/content_archive.py |
| F-63 | 归档检索回归测试 | ✅ | tests/test_content_archive.py |

---

## 2. 为什么需要原文归档

用户原始洞察（Issue #5）：SKILL.state 论文"校验后丢弃本步推理"，我们的改进是**保留原文 + 编号**，
缺原文时仍可通过索引找回，不丢上下文。此前实现了"折叠 + 编号"，但 `content_ref` 只是一个
字符串编号，**原文全文并未真正落盘**，编号无法解析回原文 —— 相当于承诺了"可恢复"却无恢复载体。

ContentArchive 正是这个"恢复载体"：

```
fold 一段原文
   │
   ▼
ContentArchive.store_segments
   │  每段原文全文 → data/state/content/<session>/<content_ref>.json
   ▼
StateCard 任务只带 content_ref（编号）
   │  执行/提交时只传 compact 上下文 + 编号引用（不携带全量）
   ▼
需要原文时
   ▼
ContentArchive.retrieve_content(session, content_ref) → 精确取回原文全文
```

---

## 3. 核心机制

### 3.1 ContentArchive 存储结构

```
data/state/content/
  └── <session_id>/
        ├── <content_ref>.json     # 每段原文一条
        └── ...
```

单条归档 JSON：
```json
{
  "session_id": "sess-full",
  "content_ref": "sess-full-seg001",
  "content": "……折叠前的原文全文……",
  "title": "段标题",
  "meta": {},
  "archived_at": "2026-09-08 02:…"
}
```

### 3.2 FoldEngine 自动联动

`fold_content(content)` 默认（`archive=True`）自动将每段原文全文归档，
并让每个任务的 `content_ref` 对应真实归档条目。之后：

- `engine.retrieve_original(session_id, content_ref)` → 取回原文全文
- `engine.search_tasks(cards, kw, include_original=True)` → 命中任务返回原文

> `archive=False` 时保持"仅折叠不归档"的旧行为，向后兼容。

### 3.3 完全解耦、可迁移

`ContentArchive` 是独立类，不依赖 StateManager / FoldEngine，可单独对任意
"要折叠但不可丢原文"的内容做归档 + 索引，便于迁移到其他仓库/单元复用。

---

## 4. 使用方式

### Python API

```python
from hanghang.engine import ContentArchive, FoldEngine, StateManager

# 1) 直接归档/取回
ca = ContentArchive()
ca.store("sess-1", "sess-1-seg001", "完整原文……")
ca.retrieve_content("sess-1", "sess-1-seg001")   # -> 完整原文
ca.list_refs("sess-1")                            # -> 该会话所有 content_ref

# 2) fold 时自动归档（默认）
fe = FoldEngine("sess-1", archive_root=None)      # None=默认 data/state/content
card = fe.fold_content("第一段……\n\n第二段……")
fe.retrieve_original("sess-1", card.tasks[0].content_ref)  # -> 找回原文

# 3) M8 跨任务检索并带回原文
results = fe.search_tasks(cards, "关键词", include_original=True)
# results[i]["original"] = 命中的原文全文（折叠后仍可找回）
```

### CLI

```bash
# 归档一段原文
python3 src/hanghang/cli/main.py state archive --session demo --ref demo-seg001 \
    --content "这段完整原文需要被折叠但可找回"

# 按 content_ref 取回原文全文
python3 src/hanghang/cli/main.py state retrieve --session demo --ref demo-seg001

# 列出某会话全部已归档 content_ref
python3 src/hanghang/cli/main.py state refs --session demo

# 展示"可恢复完整视图"：StateCard 导航 + 各折叠任务原文是否可恢复
python3 src/hanghang/cli/main.py state full --session demo
```

---

## 5. 能力索引 / 文件变更

- Python 导出：`from hanghang.engine import ContentArchive` /
  `from hanghang.state import ContentArchive`
- 数据目录：`data/state/content/<session>/<content_ref>.json`
- CLI：`state archive / retrieve / refs / full`

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/hanghang/state/content_archive.py` | 新增 | ContentArchive 原文归档检索层 |
| `src/hanghang/state/fold_engine.py` | 修改 | fold_content 自动归档 + retrieve_original + search include_original |
| `src/hanghang/state/__init__.py` | 修改 | 导出 ContentArchive |
| `src/hanghang/engine/__init__.py` | 修改 | 导出 ContentArchive |
| `src/hanghang/cli/state_commands.py` | 修改 | archive/retrieve/refs/full 实现 |
| `src/hanghang/cli/main.py` | 修改 | 注册新子命令 |
| `tests/test_content_archive.py` | 新增 | 15 项测试 |
| `docs/feature-delivery-v9.md` | 新增 | 本索引文档 |

---

## 6. 验证

- ✅ 新增 `tests/test_content_archive.py` 15 项测试全部通过
- ✅ 全量 **18 个测试文件 0 失败**（255 项测试全绿）
- ✅ CLI 冒烟：archive → retrieve → refs 端到端通过
- ✅ 边界：多空行不串位 / archive=False 不落盘 / 路径穿越拒绝 / 原子写无 .tmp 残留
