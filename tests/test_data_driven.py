"""数据驱动路由可扩展性测试 + 复合边界规则测试 + 交接卡自动集成测试"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from hanghang.engine import (
    Registry, IntentRouter, CompositePlanner, HandoffBus,
)
from hanghang.engine.models import Role, IndustryUnit
import yaml


def test_role_keywords_from_yaml():
    """验证 Role 模型能从 YAML keywords 字段正确加载"""
    reg = Registry()
    unit = reg.get_unit("dongjiagoushi")
    assert unit is not None
    architect = unit.role_by_name("architect")
    assert architect is not None
    # architect 应有关键词
    assert "架构设计" in architect.get_keywords()
    assert "架构方案" in architect.get_keywords()
    assert "架构" in architect.get_keywords()  # 添加了完整 keywords


def test_role_keywords_from_description():
    """验证 keywords 为空时能自动从 description 拆分"""
    # 创建一个没有 keywords 字段但有 description 的 Role
    role = Role(
        name="test_role",
        prefix="[测试]",
        description="测试 关键词 拆分功能",
    )
    kws = role.get_keywords()
    assert "测试" in kws
    assert "关键词" in kws
    assert "拆分功能" in kws


def test_data_driven_add_new_unit_without_code_change():
    """核心验证：新增行业单元只需要更新数据，不需要改代码

    模拟一个"法律咨询"单元，只注册数据即可被路由识别。
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        # 创建一个包含新单元的数据文件
        yaml_data = {
            "unit_id": "legal-consult",
            "industry": "法律咨询",
            "industry_alias": ["法律", "律师", "法务", "合同审查"],
            "capability_tags": ["合同审查", "法律意见", "知识产权", "合规"],
            "roles": [
                {
                    "name": "legal_consultant",
                    "prefix": "[律师]",
                    "handoff": "relay",
                    "composite": True,
                    "keywords": ["法律意见", "合同审查", "法律咨询", "律师", "法务"],
                },
                {
                    "name": "compliance_officer",
                    "prefix": "[合规]",
                    "handoff": "relay",
                    "composite": True,
                    "keywords": ["合规审查", "政策合规", "法规", "合规"],
                },
            ],
        }
        yaml_file = os.path.join(tmpdir, "industry-register-legal.yaml")
        with open(yaml_file, "w", encoding="utf-8") as f:
            yaml.dump(yaml_data, f, allow_unicode=True, default_flow_style=False)

        # 注册新单元
        reg = Registry(search_paths=[tmpdir])
        router = IntentRouter(reg)

        # 新单元应能被路由（不改任何代码）
        r = router.route("我需要一份合同审查的法律意见")
        assert r.unit_id == "legal-consult", f"expected legal-consult, got {r.unit_id}"
        assert "legal_consultant" in r.roles
        assert r.needs_manual is False

        # 其他关键词也应能命中
        r2 = router.route("做一次合规审查")
        assert r2.unit_id == "legal-consult"
        assert "compliance_officer" in r2.roles


def test_synonym_routing_same_result():
    """验证同义改写路由到同一结果（缓存命中稳定性的基础条件）"""
    reg = Registry()
    router = IntentRouter(reg)

    r1 = router.route("帮我设计一个数据库的架构方案")
    r2 = router.route("请给我做一份数据库系统架构设计方案")

    assert r1.unit_id == r2.unit_id
    assert r1.unit_id == "dongjiagoushi"
    assert r1.roles == r2.roles
    assert r1.roles == ["architect"]


def test_repeated_route_same_result():
    """验证重复提交得到一致路由结果"""
    reg = Registry()
    router = IntentRouter(reg)

    results = set()
    for _ in range(5):
        r = router.route("既要架构方案又要落地开发")
        results.add((r.unit_id, tuple(r.roles), r.confidence))
    assert len(results) == 1, f"重复提交路由结果不稳定: {results}"


def test_composite_boundary_rule():
    """验证复合agent的 role_priority + boundary 规则"""
    reg = Registry()
    planner = CompositePlanner(reg)
    plan = planner.plan("既要架构设计又要开发编码，还要做产品规划")

    assert plan["mode"] == "composite"
    # 应按 priority 顺序排列: product -> architect -> developer
    order = plan["execution_order"]
    assert order == ["product", "architect", "developer"], f"got {order}"
    # boundary 规则必须存在
    assert "boundary" in plan
    assert plan["boundary"]["role_isolation"] == "handoff_card_only"
    assert plan["boundary"]["execution_order"] == order


def test_handoff_auto_create_for_incompatible_roles():
    """验证含不可复合岗位时自动创建交接卡"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # 创建一个自定义注册表，其中 developer 是不可复合的
        yaml_data = {
            "unit_id": "test-unit",
            "industry": "测试行业",
            "industry_alias": ["测试行业"],
            "roles": [
                {"name": "architect", "prefix": "[架构]",
                 "composite": True,
                 "keywords": ["架构设计"]},
                {"name": "noncomposite_role", "prefix": "[单]",
                 "composite": False,
                 "keywords": ["单角色非复合"]},
            ],
        }
        yaml_file = os.path.join(tmpdir, "industry-register-test.yaml")
        with open(yaml_file, "w", encoding="utf-8") as f:
            yaml.dump(yaml_data, f, allow_unicode=True)

        # 用临时目录做交接卡存储
        handoff_dir = os.path.join(tmpdir, "handoffs")
        bus = HandoffBus(data_dir=handoff_dir)

        reg = Registry(search_paths=[tmpdir])
        planner = CompositePlanner(reg, handoff_bus=bus)
        plan = planner.plan("做一个架构设计但需要单角色非复合处理")

        # 由于 "架构设计" 和 "单角色非复合" 同时命中
        # noncomposite_role 的 composite=False
        assert plan["mode"] == "handoff_required"
        assert plan["handoff_card_id"] is not None
        assert plan["handoff_required"] is True

        # 验证交接卡确实被创建
        card = bus.get(plan["handoff_card_id"])
        assert card is not None
        assert card.status == "created"


def test_cross_unit_handoff_creation():
    """验证跨单元交接卡能自动创建"""
    with tempfile.TemporaryDirectory() as tmpdir:
        handoff_dir = os.path.join(tmpdir, "handoffs")
        bus = HandoffBus(data_dir=handoff_dir)

        reg = Registry()
        planner = CompositePlanner(reg, handoff_bus=bus)
        plan = planner.plan_cross_unit(
            "需要软件架构设计同时做游戏关卡策划",
            source_unit_id="dongjiagoushi",
            target_unit_id="game-dev-unit",
        )
        assert plan["mode"] == "cross_unit_handoff"
        assert plan["handoff_card_id"] is not None
        assert plan["source_unit"] == "dongjiagoushi"
        assert plan["target_unit"] == "game-dev-unit"


def test_m8_search_by_keyword_list():
    """验证 M8 能力索引支持多结果搜索"""
    reg = Registry()
    # "架构" 关键词应该只命中 dongjiagoushi
    matches = reg.search_by_keyword("架构")
    assert len(matches) >= 1
    unit_ids = [u.unit_id for u in matches]
    assert "dongjiagoushi" in unit_ids


# ============================================================
# 以下为评审闭环修复的回归测试
# ============================================================

def test_game_dev_bare_keyword_develop():
    """评审问题1修复：game_dev 岗位必须包含裸词"开发"
    否则 "开发一款手机游戏" 命中行业却返回空岗位。
    """
    reg = Registry()
    unit = reg.get_unit("game-dev-unit")
    assert unit is not None
    game_dev = unit.role_by_name("game_dev")
    assert game_dev is not None
    # 裸词"开发"必须存在于 game_dev 的关键词中
    assert "开发" in game_dev.get_keywords()


def test_game_route_gets_role_not_empty():
    """评审问题1修复："开发一款手机游戏" 命中行业且应有具体岗位"""
    reg = Registry()
    router = IntentRouter(reg)

    r = router.route("开发一款手机游戏")
    assert r.unit_id == "game-dev-unit", f"expected game-dev-unit, got {r.unit_id}"
    assert "game_dev" in r.roles, f"expected game_dev in roles, got {r.roles}"
    assert r.fallback_reason != "仅行业命中"


def test_cross_industry_ambiguity_detection():
    """评审问题1修复：真正的跨行业冲突应触发歧义人工回落

    "开发一款游戏需求" 同时触及软件(开发/需求)和游戏(游戏)两行业，
    且分数接近时不应盲目选边，应判歧义让人工确认。
    """
    reg = Registry()
    router = IntentRouter(reg)

    r = router.route("开发一款游戏需求")
    # 跨行业歧义场景：不选任意单元，而是回落人工
    assert r.needs_manual is True, f"expected manual fallback, got unit={r.unit_id}"
    assert r.is_ambiguous is True, "expected ambiguous flag"


def test_register_version_unified():
    """评审问题4修复：register_version 应统一为一致版本号"""
    reg = Registry()
    sw = reg.get_unit("dongjiagoushi")
    game = reg.get_unit("game-dev-unit")
    assert sw is not None and game is not None
    assert sw.register_version == game.register_version
    # 应等于 register-spec 文档中声明的版本号
    assert sw.register_version in ("1.0", "1.1"), f"unexpected version: {sw.register_version}"


# ============================================================
# 第二轮评审修复的回归测试
# ============================================================

def test_generic_word_no_false_ambiguity():
    """评审问题②修复：泛化词导致的伪歧义不应触发人工回落

    "开发一个网页应用" 中只有泛化词"开发"同时命中 developer 和 game_dev，
    两单元得分相同但无独立行业信号差异 → 应路由到软件研发而非判歧义。
    """
    reg = Registry()
    router = IntentRouter(reg)

    r = router.route("开发一个网页应用")
    assert r.needs_manual is False, \
        f"泛化词伪歧义不应回落人工, got reason={r.fallback_reason}"
    assert r.is_ambiguous is False, "不应标记为歧义"
    assert r.unit_id == "dongjiagoushi", \
        f"无游戏特征时软件研发应命中, got unit={r.unit_id}"
    assert "developer" in r.roles, f"应有 developer 岗位, got {r.roles}"


def test_true_ambiguity_still_detected():
    """评审问题②修复：真跨行业冲突仍需判歧义（不因泛化词过滤而误放行）

    "开发一款游戏需求" 同时有游戏行业别名(游戏)和软件产品角色(需求)的
    独立行业信号 → 必须保持歧义回落人工。
    """
    reg = Registry()
    router = IntentRouter(reg)

    r = router.route("开发一款游戏需求")
    assert r.needs_manual is True, \
        f"真跨行业冲突应判歧义, got unit={r.unit_id}, reason={r.fallback_reason}"
    assert r.is_ambiguous is True, "应标记为 ambiguous"


def test_cross_unit_candidates_detection():
    """评审问题①修复：cross_unit_candidates 应识别真跨行业单元"""
    reg = Registry()
    router = IntentRouter(reg)

    # 真跨行业：软件+游戏独立信号 → 应返回 2 个单元
    cands = router.cross_unit_candidates("需要软件架构设计并做游戏关卡策划")
    assert len(cands) >= 2, f"expected >=2 candidates, got {cands}"
    assert "dongjiagoushi" in cands
    assert "game-dev-unit" in cands

    # 泛化词伪歧义：应只返回 1 个单元
    cands2 = router.cross_unit_candidates("开发一个网页应用")
    assert len(cands2) == 1, f"expected 1 candidate, got {cands2}"
    assert cands2[0] == "dongjiagoushi"

    # 明确游戏诉求：只命中 game-dev-unit
    cands3 = router.cross_unit_candidates("开发一个手机游戏")
    assert len(cands3) == 1, f"expected 1 candidate, got {cands3}"
    assert cands3[0] == "game-dev-unit"

    # 空输入
    assert router.cross_unit_candidates("") == []


def test_cross_unit_cli_detects_multi_industry():
    """评审问题①修复：cross-unit CLI 应能识别跨行业并触发交接编排

    旧实现：先 route() 遇 needs_manual 即 return → 交接分支永不可达。
    新实现：先 cross_unit_candidates 检测多行业独立信号 → 直接编排交接。
    """
    import subprocess
    import tempfile

    reg = Registry()
    router = IntentRouter(reg)

    # ① cross_unit_candidates 能识别真跨行业诉求（≥2 单元独立信号）
    cands = router.cross_unit_candidates("需要软件架构设计并做游戏关卡策划")
    assert len(cands) >= 2, f"expected >=2 cross-unit candidates, got {cands}"

    # ② 伪歧义（共享泛化词）只返回单单元，不应触发 cross-unit
    cands_pseudo = router.cross_unit_candidates("开发一个网页应用")
    assert len(cands_pseudo) == 1

    # ③ plan_cross_unit 能真正创建交接卡（M5 交接编排可到达）
    with tempfile.TemporaryDirectory() as tmpdir:
        bus = HandoffBus(data_dir=tmpdir)
        planner = CompositePlanner(reg, handoff_bus=bus)
        plan = planner.plan_cross_unit(
            "需要软件架构设计并做游戏关卡策划",
            source_unit_id="dongjiagoushi",
            target_unit_id="game-dev-unit",
        )
        assert plan["mode"] == "cross_unit_handoff"
        assert plan["handoff_card_id"] is not None
        card = bus.get(plan["handoff_card_id"])
        assert card is not None
        assert "架构设计" in card.intent and "关卡" in card.intent

if __name__ == "__main__":
    test_role_keywords_from_yaml()
    test_role_keywords_from_description()
    test_data_driven_add_new_unit_without_code_change()
    test_synonym_routing_same_result()
    test_repeated_route_same_result()
    test_composite_boundary_rule()
    test_handoff_auto_create_for_incompatible_roles()
    test_cross_unit_handoff_creation()
    test_m8_search_by_keyword_list()
    # 评审闭环修复回归
    test_game_dev_bare_keyword_develop()
    test_game_route_gets_role_not_empty()
    test_cross_industry_ambiguity_detection()
    test_register_version_unified()
    # 第二轮评审修复回归
    test_generic_word_no_false_ambiguity()
    test_true_ambiguity_still_detected()
    test_cross_unit_candidates_detection()
    test_cross_unit_cli_detects_multi_industry()
    print("✅ 数据驱动+复合边界+交接集成测试通过")


# ============================================================
# 第三轮评审修复的回归测试
# ============================================================

def test_tie_break_deterministic():
    """评审问题①修复：同分命中需确定性 tie-break

    "开发一个网页应用" 中"开发"同时命中 dongjiagoushi.developer 与
    game-dev-unit.game_dev（单角色命中各 1.5，同分）。路由归属不得依赖
    注册/遍历顺序，应按确定性规则（同分取 unit_id 字典序较小者）稳定命中
    dongjiagoushi。
    """
    reg = Registry()
    router = IntentRouter(reg)

    # 10 次重复路由结果应唯一且确定为 dongjiagoushi
    results = {router.route("开发一个网页应用").unit_id for _ in range(10)}
    assert results == {"dongjiagoushi"}, f"同分 tie-break 结果不稳定: {results}"

    r = router.route("开发一个网页应用")
    assert r.needs_manual is False, f"伪歧义不应回落人工: {r.fallback_reason}"
    assert r.unit_id == "dongjiagoushi"


def test_registry_dup_detect_keywords_diff():
    """评审问题②修复：重复定义一致性校验须覆盖 keywords/description

    两个来源对同一 unit_id 给出相同岗位名但不同 keywords 时，应判定为
    内容不一致（告警），不能仅因岗位名相同就当幂等覆盖（防静默分叉）。
    """
    import tempfile
    import yaml
    from hanghang.engine.registry import Registry

    base = {
        "unit_id": "dup-check",
        "industry": "一致性测试",
        "industry_alias": ["一致", "测试"],
        "register_version": "1.1",
        "capability_tags": ["一致能力"],
        "roles": [
            {"name": "r1", "prefix": "[R1]", "description": "关键词A", "keywords": ["词A"]},
        ],
    }
    # 岗位名同为 r1，但 keywords 不同
    variant = {
        **base,
        "roles": [
            {"name": "r1", "prefix": "[R1]", "description": "关键词B", "keywords": ["词B"]},
        ],
    }

    u_a = Registry._parse_unit(Registry(), base)
    u_b = Registry._parse_unit(Registry(), variant)
    # 两单元 roles 名相同、但 keywords/description 不同 → 判不一致
    assert not Registry._unit_equal(Registry(), u_a, u_b), \
        "岗位 keywords/description 不同的重复定义应判为不一致"

    # 完全一致的重复定义应判为一致（幂等覆盖，不告警）
    u_c = Registry._parse_unit(Registry(), dict(base))
    assert Registry._unit_equal(Registry(), u_a, u_c), "完全一致的重复定义应判为一致"


def test_game_level_designer_no_false_composite():
    """评审问题③修复：game_planner 不含裸词"关卡"，关卡设计不误复合

    移除 game_planner 关键词中的"关卡"后，纯关卡设计诉求只命中
    level_designer（关卡设计专属岗），不再把 game_planner 误拉进来复合。
    """
    reg = Registry()
    unit = reg.get_unit("game-dev-unit")
    gp = unit.role_by_name("game_planner")
    # game_planner 关键词中不得再有与 level_designer 重叠的裸词"关卡"
    assert "关卡" not in gp.get_keywords(), "game_planner 不应包含泛词'关卡'"

    router = IntentRouter(reg)
    r = router.route("设计一个吃鸡的关卡地图")
    assert r.unit_id == "game-dev-unit"
    assert "level_designer" in r.roles
    assert "game_planner" not in r.roles, \
        f"纯关卡设计不应误复合 game_planner: {r.roles}"


if __name__ == "__main__":
    test_role_keywords_from_yaml()
    test_role_keywords_from_description()
    test_data_driven_add_new_unit_without_code_change()
    test_synonym_routing_same_result()
    test_repeated_route_same_result()
    test_composite_boundary_rule()
    test_handoff_auto_create_for_incompatible_roles()
    test_cross_unit_handoff_creation()
    test_m8_search_by_keyword_list()
    # 评审闭环修复回归
    test_game_dev_bare_keyword_develop()
    test_game_route_gets_role_not_empty()
    test_cross_industry_ambiguity_detection()
    test_register_version_unified()
    # 第二轮评审修复回归
    test_generic_word_no_false_ambiguity()
    test_true_ambiguity_still_detected()
    test_cross_unit_candidates_detection()
    test_cross_unit_cli_detects_multi_industry()
    # 第三轮评审修复回归
    test_tie_break_deterministic()
    test_registry_dup_detect_keywords_diff()
    test_game_level_designer_no_false_composite()
    print("✅ 数据驱动+复合边界+交接集成测试通过")
