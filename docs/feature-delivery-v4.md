# 功能特性交付索引（M10 上下文装配器）

> 版本：M10 上下文装配器（防冗余规则）| 2026-09-07 | 落地：架构·开发(CodeBuddy)
> 场景：Issue #11 防提示词冗余
> 前置设计：架构·总师 M10 设计文档（评论 2096634574514262016）

---

## 1. 总览

M10 解决 Issue #11 核心诉求——**防止每次提交带全部提示词**。通过三层物理隔离 + 按规则注入机制，把"每次全量上送"改为"静态常驻 + 会话态按需 + 局部按规则注入"。

| 功能编号 | 功能名称 | 状态 | 涉及文件 |
|---------|---------|------|---------|
| F-27 | M10-a 三层上下文装配器 | ✅ | src/hanghang/context/assembler.py |
| F-28 | M10-b 声明式规则表引擎 (R3) | ✅ | src/hanghang/context/rules.py + data/context-rules.yaml |
| F-29 | M10-c 引用检索（复用 M9） | ✅ | 复用 src/hanghang/state/fold_engine.py |
| F-30 | M10-d 缓存保护（静态/动态隔离） | ✅ | src/hanghang/context/cache_guard.py |
| F-31 | M10 全量回归测试 | ✅ | tests/test_context_m10.py |

---

## 2. 实现架构

### 三层物理隔离

```
层A【静态·缓存键】角色 + 前缀 + 契约   → cache_key 只看这层
层B【会话态】StateCard 展开要素         → compact_context
层C【注入·按规则】局部动作相关片段      → 独立注入，与A完全隔离
```

### 六条防冗余规则

| 编号 | 规则 | 实现 |
|------|------|------|
| R1 | 角色静态注册不随行 | M3 PrefixArchive 复用 |
| R2 | 一人一对话 | M4/M5 复用 |
| **R3** | **本地规则触发不靠全量** | **M10-b RuleEngine 新增** |
| R4 | 原文落盘+引用 | M9 FoldEngine 复用 |
| **R5** | **动态与静态隔离** | **M10-d CacheGuard 新增** |
| R6 | 增量而非全量 | M9 compact_context 复用 |

---

## 3. 核心功能详述

### F-27 M10-a 三层上下文装配器

```python
from hanghang.context import ContextAssembler, RuleEngine, CacheGuard

assembler = ContextAssembler(
    rule_engine=RuleEngine(),       # M10-b
    source_providers={               # 数据源注入器
        "file.diff": lambda ctx: "...",
    },
)
result = assembler.assemble(
    session_id="sess-1", role_name="secretary", unit_id="dongjiagoushi",
    user_text="帮我修改代码", static_prefix="[秘书]",
)
# result = { layer_a, layer_b, layer_c, full_context, hit_rules, cache_key, layer_sizes }
```

**缓存保护**：`cache_key` 仅由层A哈希生成，任何动态上下文(层B/C)变化不影响缓存命中。

### F-28 M10-b 声明式规则表（R3核心）

- **数据结构**：`ContextRule { rule_id, name, triggers, target_layer, data_source, priority, match_mode }`
- **默认规则**：6条（文件操作/状态管理/交接/架构/测试/数据配置）
- **声明式承载**：`data/context-rules.yaml` 数据驱动，改规则不改代码
- **触发匹配**：关键词包含 / 正则表达式两种模式

### F-29 M10-c 引用检索

复用 M9 `FoldEngine.resolve_ref()`，通过 `content_ref` 精确检索折叠任务原文，不携带全量。

### F-30 M10-d 缓存保护

```python
guard = CacheGuard()
check = guard.validate_isolation(layer_a, session_id="sess-1")
# check = { valid, violations, cache_hit, layer_a_signature, stats }
```

- 检测层A中是否混入动态内容标记
- 验证同session内层A签名稳定 → 缓存命中率
- 提供缓存保护统计指标

---

## 4. 数据文件

| 路径 | 类型 | 说明 |
|------|------|------|
| `data/context-rules.yaml` | 声明式 | M10 上下文装配触发规则表 |
| `src/hanghang/context/rules.py` | 核心 | M10-b 规则引擎 |
| `src/hanghang/context/assembler.py` | 核心 | M10-a 三层装配器 |
| `src/hanghang/context/cache_guard.py` | 核心 | M10-d 缓存保护 |
| `tests/test_context_m10.py` | 新增 | M10 全量回归测试 |
| `docs/architecture/M10-上下文装配-防冗余规则.md` | 文档 | M10 架构设计文档 |

---

## 5. 测试覆盖

- **13 个测试文件全绿**（含新增 `test_context_m10.py`），**141 个测试通过**，失败 0。
- 新增 M10 专项测试 **19 项**：规则引擎(8)、装配器(4)、缓存保护(6)、声明式文件(1)。
- CLI 冒烟测试通过。

---

## 6. 与调度任务对齐

- Issue #11「防止提示词冗余」核心诉求：✅ M10 三层装配 + R3 规则表 + R5 缓存隔离落地。
- 前置 M1-M9 全部落地并测试通过。
- **遗留问题**（超本 Issue 范围，另开 Issue 处理）。
