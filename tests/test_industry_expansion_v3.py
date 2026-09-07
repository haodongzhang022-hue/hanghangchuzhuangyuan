"""行业横向扩展第三期测试：教育培训/健康医疗/家装设计

本期开发要点：
1. 行业单元从 8 扩展至 11（新增 教育培训/健康医疗/家装设计），纯数据驱动。
2. 填补此前大量常见场景（课程培训/心理咨询/家装设计等）无法识别、回落人工的盲区。
3. 确保扩展不破坏原有行业路由稳定性（回归护栏）。
"""
import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from hanghang.engine import Registry, IntentRouter


def test_eleven_industries_registered():
    """11 个行业单元均已注册"""
    reg = Registry()
    ids = {u.unit_id for u in reg.all_units()}
    assert {"dongjiagoushi", "game-dev-unit", "legal-services",
            "content-creation", "data-analytics", "e-commerce",
            "finance-accounting", "marketing", "education-training",
            "healthcare", "home-design"} <= ids


def test_education_training_route():
    """教育培训：课程设计→curriculum_designer，学英语→learning_advisor，家教→teacher"""
    reg = Registry()
    router = IntentRouter(reg)

    # 课程/培训方案
    r = router.route("帮我设计一个英语培训方案")
    assert r.unit_id == "education-training", f"got {r.unit_id}"
    assert "curriculum_designer" in r.roles

    # 学习/报课
    r2 = router.route("帮我制定英语学习计划")
    assert r2.unit_id == "education-training"
    assert "learning_advisor" in r2.roles

    # 教师/家教
    r3 = router.route("帮我找一个英语家教")
    assert r3.unit_id == "education-training"
    assert "teacher" in r3.roles

    # 备课教案
    r4 = router.route("请帮我备一节数学课")
    assert r4.unit_id == "education-training"
    assert "curriculum_designer" in r4.roles


def test_healthcare_route():
    """健康医疗：体检解读→health_consultant，心理咨询→psychologist，就医→medical_advisor"""
    reg = Registry()
    router = IntentRouter(reg)

    # 健康/体检
    r = router.route("帮我解读一下体检报告")
    assert r.unit_id == "healthcare", f"got {r.unit_id}"
    assert "health_consultant" in r.roles

    # 心理咨询
    r2 = router.route("我最近压力大想找心理咨询师")
    assert r2.unit_id == "healthcare"
    assert "psychologist" in r2.roles

    # 就医建议
    r3 = router.route("我头疼应该去哪个科室看")
    assert r3.unit_id == "healthcare"
    assert "medical_advisor" in r3.roles

    # 健身计划
    r4 = router.route("帮我制定一个健身计划")
    assert r4.unit_id == "healthcare"
    assert "fitness_coach" in r4.roles


def test_home_design_route():
    """家装设计：室内设计→interior_designer，软装→soft_furnish，装修→project_manager"""
    reg = Registry()
    router = IntentRouter(reg)

    # 室内/家装设计
    r = router.route("帮我做个卧室装修方案")
    assert r.unit_id == "home-design", f"got {r.unit_id}"
    assert "interior_designer" in r.roles

    # 软装搭配
    r2 = router.route("帮我做客厅的软装搭配")
    assert r2.unit_id == "home-design"
    assert "soft_furnish" in r2.roles

    # 找装修公司
    r3 = router.route("我想装修房子，帮我找一家装修公司")
    assert r3.unit_id == "home-design"
    assert "project_manager" in r3.roles


def test_existing_industries_stable_after_v3_expansion():
    """新增 3 行业后，原有行业路由不回归"""
    reg = Registry()
    router = IntentRouter(reg)
    cases = {
        "帮我做个网站": "dongjiagoushi",
        "帮我做架构设计": "dongjiagoushi",
        "帮我设计一款游戏": "game-dev-unit",
        "帮我审核一份合同": "legal-services",
        "帮我写一篇公众号文章": "content-creation",
        "帮我做一份数据报表": "data-analytics",
        "帮我在淘宝开个店": "e-commerce",
        "帮我做账报税": "finance-accounting",
        "帮我做一份营销策划": "marketing",
    }
    for text, expected in cases.items():
        r = router.route(text)
        assert r.unit_id == expected, \
            f"{text} 应路由到 {expected}，实际 {r.unit_id}"


def test_new_industries_do_not_overreach():
    """新增行业不应过度抢占意图：非新行业场景不应被静默路由到新行业"""
    reg = Registry()
    router = IntentRouter(reg)
    # 以下均不是教育/健康/家装意图，不应被静默路由
    non_overreach = [
        "帮我写一篇产品文案",
        "帮我做系统架构",
        "帮我做数据分析报告",
    ]
    for text in non_overreach:
        r = router.route(text)
        assert r.unit_id not in {"education-training", "healthcare", "home-design"} or \
            r.needs_manual, \
            f"{text} 不应被静默路由到新增行业，实际 {r.unit_id}"


def test_prefix_archive_has_11_units():
    """prefix-archive.json 含全部 11 个行业单元"""
    archive_path = os.path.join(
        os.path.dirname(__file__), "../data/prefix-archive.json")
    assert os.path.exists(archive_path)
    with open(archive_path, "r", encoding="utf-8") as f:
        archive = json.load(f)
    expected = {"dongjiagoushi", "game-dev-unit", "legal-services",
                "content-creation", "data-analytics", "e-commerce",
                "finance-accounting", "marketing", "education-training",
                "healthcare", "home-design"}
    assert expected <= set(archive.keys()), \
        f"prefix-archive 缺少: {expected - set(archive.keys())}"


if __name__ == "__main__":
    test_eleven_industries_registered()
    test_education_training_route()
    test_healthcare_route()
    test_home_design_route()
    test_existing_industries_stable_after_v3_expansion()
    test_new_industries_do_not_overreach()
    test_prefix_archive_has_11_units()
    print("✅ 行业扩展第三期测试通过")
