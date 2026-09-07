"""M10 上下文装配器测试：防冗余规则表(R3) + 三层装配 + 缓存保护"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from hanghang.context import (
    ContextRule, RuleEngine, ContextAssembler,
    CacheGuard, default_rules,
)


# ============ M10-b 规则引擎测试 ============

def test_default_rules_exist():
    """默认规则集非空且含关键规则"""
    rules = default_rules()
    assert len(rules) >= 6
    rule_ids = [r.rule_id for r in rules]
    assert "R3-FILE-01" in rule_ids
    assert "R3-STAT-01" in rule_ids
    assert "R3-HAND-01" in rule_ids
    assert "R3-ARCH-01" in rule_ids


def test_rule_match_keyword():
    """关键词命中"""
    rule = ContextRule(
        rule_id="T-01", name="测试",
        triggers=["修改", "文件"], target_layer="C",
    )
    assert rule.match("帮我修改这个文件") is True
    assert rule.match("帮我写一篇散文") is False


def test_rule_match_inactive():
    """禁用规则不命中"""
    rule = ContextRule(
        rule_id="T-02", name="测试", enabled=False,
        triggers=["文件"], target_layer="C",
    )
    assert rule.match("修改文件") is False


def test_rule_match_mode_regex():
    """正则匹配模式"""
    rule = ContextRule(
        rule_id="T-03", name="正则测试",
        triggers=[r"\.py$", r"测试\d+"], target_layer="C",
        match_mode="regex",
    )
    assert rule.match("module.py") is True
    assert rule.match("测试123") is True
    assert rule.match("plain text") is False


def test_rule_engine_match_returns_hits():
    """RuleEngine 匹配返回按优先级排序的命中规则"""
    engine = RuleEngine()  # 使用内置默认规则
    hits = engine.match("帮我修改 src/hanghang/context/assembler.py 这个文件")
    # 应命中 FILE-01（文件操作）
    assert any(r.rule_id == "R3-FILE-01" for r in hits)
    # 优先级：FILE-01(priority=5) 应先于 ARCH-01(priority=7)
    assert hits[0].priority <= hits[-1].priority


def test_rule_engine_no_match():
    """无命中返回空列表"""
    engine = RuleEngine()
    hits = engine.match("今天天气怎么样？")
    assert hits == []


def test_rule_engine_layer_filter():
    """按层过滤"""
    engine = RuleEngine()
    hits = engine.match_by_layer(
        "修改代码测试状态管理", layer="C")
    for r in hits:
        assert r.target_layer == "C"


def test_rule_from_yaml_file():
    """从声明式YAML文件加载规则（数据驱动）"""
    rules_file = os.path.join(
        os.path.dirname(__file__), "../data/context-rules.yaml")
    if os.path.exists(rules_file):
        engine = RuleEngine(rules_file)
        rules = engine.list_rules()
        assert len(rules) >= 6
        ids = [r.rule_id for r in rules]
        assert "R3-FILE-01" in ids
        assert "R3-STAT-01" in ids


# ============ M10-a 装配器测试 ============

def test_assembler_three_layers():
    """装配器输出三层结构且隔离"""
    assembler = ContextAssembler()
    result = assembler.assemble(
        session_id="sess-1",
        role_name="secretary",
        unit_id="dongjiagoushi",
        user_text="帮我修改代码实现测试",
        static_prefix="[秘书]",
        objective="测试装配器",
    )

    # 三层存在
    assert "layer_a" in result
    assert "layer_b" in result
    assert "layer_c" in result
    assert "full_context" in result

    # 层A含静态内容
    assert "session_context_static=true" in result["layer_a"]
    assert "secretary" in result["layer_a"]

    # 层B含目标
    assert "目标: 测试装配器" in result["layer_b"]

    # 命中规则列表存在
    assert "hit_rules" in result
    assert "hit_rule_ids" in result

    # 完整上下文包含各层标记
    assert "### 静态上下文" in result["full_context"]


def test_assembler_cache_key_stability():
    """缓存键仅基于层A生成且保持稳定"""
    assembler = ContextAssembler()

    result1 = assembler.assemble(
        session_id="s1",
        role_name="secretary",
        unit_id="dongjiagoushi",
        user_text="修改代码",     # 不同动态内容
        static_prefix="[秘书]",
        objective="目标1",
    )
    result2 = assembler.assemble(
        session_id="s1",
        role_name="secretary",
        unit_id="dongjiagoushi",
        user_text="做架构设计",   # 不同动态内容
        static_prefix="[秘书]",
        objective="目标2",       # 不同动态内容
    )

    # 层A内容应该相同（静态），缓存键稳定
    assert result1["layer_a"] == result2["layer_a"]
    assert result1["cache_key"] == result2["cache_key"]


def test_assembler_state_card_layer_b():
    """StateCard 信息映射到层B"""
    from hanghang.state.models import StateCard

    card = StateCard(
        session_id="sess-b",
        objective="完成M10实现",
    )
    card.add_task(
        title="实现装配器",
        task_type="deliverable",
        files_touched=["assembler.py"],
    )

    assembler = ContextAssembler(
        source_providers={
            "state.card": lambda ctx: (
                f"目标: 完成M10实现\n"
                f"会话: {ctx['session_id']}\n"
                f"任务: 实现装配器"
            ),
        }
    )
    result = assembler.assemble(
        session_id="sess-b",
        user_text="查看当前任务状态",
        static_prefix="[秘书]",
    )

    assert isinstance(result["cache_key"], str)
    assert len(result["cache_key"]) > 0
    # 命中状态规则 STAT-01
    assert "R3-STAT-01" in result["hit_rule_ids"]


def test_assembler_with_source_providers():
    """自定义数据源 provider 注入层C"""
    assembler = ContextAssembler(
        source_providers={
            "file.diff": lambda ctx: "diff --git a/foo.py b/foo.py\n+print('hello')",
            "test.code": lambda ctx: "def test_foo():\n    assert True",
        }
    )
    result = assembler.assemble(
        session_id="s1",
        user_text="帮我修改代码并补充测试",
        static_prefix="[秘书]",
    )

    # 应命中 FILE-01 和 TEST-01，注入文件diff和测试代码
    hit_ids = result["hit_rule_ids"]
    assert "R3-FILE-01" in hit_ids
    assert "R3-TEST-01" in hit_ids

    # 层C包含注入片段
    assert "diff --git" in result["layer_c"]
    assert "def test_foo" in result["layer_c"]


# ============ M10-d 缓存保护测试 ============

def test_cache_guard_valid():
    """合法层A通过校验"""
    guard = CacheGuard()
    result = guard.validate_isolation(
        layer_a="[秘书] | secretary | unit=dongjiagoushi | session_context_static=true",
        session_id="sess-1",
    )
    assert result["valid"] is True
    assert result["violations"] == []


def test_cache_guard_dynamic_in_layer_a():
    """层A含动态标记 → 违反隔离"""
    guard = CacheGuard()
    result = guard.validate_isolation(
        layer_a="[秘书] | ### 会话态上下文 ### 目标: xxx | session_context_static=true",
        session_id="sess-1",
    )
    assert result["valid"] is False
    assert len(result["violations"]) > 0


def test_cache_guard_missing_static_mark():
    """层A缺少静态标记 → 违反"""
    guard = CacheGuard()
    result = guard.validate_isolation(
        layer_a="[秘书] | secretary",  # 没有 static=true
        session_id="sess-1",
    )
    assert result["valid"] is False


def test_cache_guard_same_session_hit():
    """同session内层A不变 → 缓存命中"""
    guard = CacheGuard()
    layer_a = "[秘书] | secretary | unit=dongjiagoushi | session_context_static=true"

    r1 = guard.validate_isolation(layer_a, "sess-hit")
    r2 = guard.validate_isolation(layer_a, "sess-hit")
    assert r2["cache_hit"] is True
    assert r2["stats"]["cache_hits"] == 1


def test_cache_guard_changed_layer_a_miss():
    """层A变化 → 缓存失效"""
    guard = CacheGuard()
    r1 = guard.validate_isolation(
        "[秘书] | secretary | unit=dongjiagoushi | session_context_static=true",
        "sess-miss",
    )
    r2 = guard.validate_isolation(
        "[秘书] | secretary | unit=other | session_context_static=true",
        "sess-miss",
    )
    assert r2["cache_hit"] is False
    assert len(r2["violations"]) > 0  # 签名变化产生violation


def test_cache_guard_end_to_end():
    """端到端：装配器 + 缓存保护"""
    assembler = ContextAssembler()
    guard = CacheGuard()

    # 第一次装配
    result1 = assembler.assemble(
        session_id="e2e-1",
        role_name="secretary",
        unit_id="dongjiagoushi",
        user_text="修改代码实现功能",
        static_prefix="[秘书]",
        objective="目标A",
    )
    check1 = guard.validate_isolation(result1["layer_a"], "e2e-1")
    assert check1["valid"] is True

    # 第二次装配（同session，不同动态内容）
    result2 = assembler.assemble(
        session_id="e2e-1",
        role_name="secretary",
        unit_id="dongjiagoushi",
        user_text="写测试用例",
        static_prefix="[秘书]",
        objective="目标B",
    )
    check2 = guard.validate_isolation(result2["layer_a"], "e2e-1")
    # 层A不变 → 缓存命中
    assert check2["cache_hit"] is True
    assert result1["cache_key"] == result2["cache_key"]


# ============ 规则表声明文件测试 ============

def test_rule_table_file_matches_defaults():
    """声明式规则表文件与内置默认规则一致性"""
    import yaml
    rules_file = os.path.join(
        os.path.dirname(__file__), "../data/context-rules.yaml")
    if os.path.exists(rules_file):
        with open(rules_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert "version" in data
        assert "rules" in data
        assert len(data["rules"]) >= 6
        # 每个规则都有 rule_id
        for rule in data["rules"]:
            assert "rule_id" in rule
            assert "triggers" in rule
            assert "target_layer" in rule
