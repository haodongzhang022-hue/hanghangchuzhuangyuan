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
    print("✅ 数据驱动+复合边界+交接集成测试通过")
