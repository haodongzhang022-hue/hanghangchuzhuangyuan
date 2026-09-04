"""路由引擎自动化测试"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from hanghang.engine import Registry, IntentRouter, CompositePlanner


def setup_registry():
    return Registry()


def test_single_route_architect():
    """单岗位直连：架构设计"""
    reg = setup_registry()
    router = IntentRouter(reg)
    r = router.route("数据库架构设计方案")
    assert r.unit_id == "dongjiagoushi"
    assert r.roles == ["architect"], f"expected architect, got {r.roles}"
    assert r.needs_manual is False


def test_single_route_developer():
    """单岗位直连：开发"""
    reg = setup_registry()
    router = IntentRouter(reg)
    r = router.route("把路由模块开发并编码实现")
    assert r.unit_id == "dongjiagoushi"
    assert r.roles == ["developer"], f"expected developer, got {r.roles}"


def test_single_route_product():
    """单岗位直连：产品"""
    reg = setup_registry()
    router = IntentRouter(reg)
    r = router.route("规划新产品需求排期")
    assert r.unit_id == "dongjiagoushi"
    assert r.roles == ["product"], f"expected product, got {r.roles}"


def test_composite_route():
    """复合路由：架构 + 开发"""
    reg = setup_registry()
    planner = CompositePlanner(reg)
    plan = planner.plan("既要架构设计又要落地开发")
    assert plan["mode"] == "composite"
    assert plan["roles"] == ["architect", "developer"], f"got {plan['roles']}"
    assert len(plan["session_prefix_set"]) == 2


def test_manual_fallback():
    """低置信回落 L2 人工"""
    reg = setup_registry()
    router = IntentRouter(reg)
    r = router.route("帮我点个外卖")
    assert r.needs_manual is True


def test_game_unit_routing():
    """游戏行业单元路由"""
    reg = setup_registry()
    router = IntentRouter(reg)
    r = router.route("做一个吃鸡游戏的关卡设计")
    assert r.unit_id == "game-dev-unit"
    assert "game_planner" in r.roles
    assert "level_designer" in r.roles


def test_software_dev_composite():
    """软件团队复合任务"""
    reg = setup_registry()
    router = IntentRouter(reg)
    r = router.route("软件开发团队需要架构方案然后落地开发")
    assert r.unit_id == "dongjiagoushi"
    assert "architect" in r.roles
    assert "developer" in r.roles


if __name__ == "__main__":
    test_single_route_architect()
    test_single_route_developer()
    test_single_route_product()
    test_composite_route()
    test_manual_fallback()
    test_game_unit_routing()
    test_software_dev_composite()
    print("✅ 全部测试通过")
