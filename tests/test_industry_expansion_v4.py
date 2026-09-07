"""行业横向扩展第四期测试：人力资源/行政办公/视觉设计

本期要点（承接 ISSUE #19 覆盖缺口推进 · 高优先级）：
1. 行业单元从 11 扩展至 14（新增 人力资源 hr-services / 行政办公 admin-office /
   视觉设计 design-visual），纯数据驱动，目标全集 coverage 同步校准。
2. 填补此前高频诉求（招聘/离职/薪酬绩效、公文/档案/会务、海报/UI/插画/品牌视觉等）
   无法识别、回落人工的盲区。
3. 通过 coverage 进度断言证明覆盖率实质提升（11/32 → 14/32），并保持原行业路由稳定。
"""
import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from hanghang.engine import Registry, IntentRouter
from hanghang.engine.coverage import CoverageTracker


def test_fourteen_industries_registered():
    """14 个行业单元均已注册"""
    reg = Registry()
    ids = {u.unit_id for u in reg.all_units()}
    assert {"dongjiagoushi", "game-dev-unit", "legal-services",
            "content-creation", "data-analytics", "e-commerce",
            "finance-accounting", "marketing", "education-training",
            "healthcare", "home-design",
            "hr-services", "admin-office", "design-visual"} <= ids


def test_hr_services_route():
    """人力资源：招聘→recruiter，离职→employee_relations，人力规划→hr_advisor，绩效→comp_benefits"""
    reg = Registry()
    router = IntentRouter(reg)

    r = router.route("帮我写一份招聘方案")
    assert r.unit_id == "hr-services", f"got {r.unit_id}"
    assert "recruiter" in r.roles

    r2 = router.route("帮我处理员工离职手续")
    assert r2.unit_id == "hr-services"
    assert "employee_relations" in r2.roles

    r3 = router.route("帮我做人力资源规划定岗定编")
    assert r3.unit_id == "hr-services"
    assert "hr_advisor" in r3.roles

    r4 = router.route("帮我设计一套薪酬绩效管理办法")
    assert r4.unit_id == "hr-services"
    assert "comp_benefits" in r4.roles


def test_admin_office_route():
    """行政办公：办公采购→admin_specialist，公文→document_archivist，会务→meeting_coordinator，前台→receptionist"""
    reg = Registry()
    router = IntentRouter(reg)

    r = router.route("帮我采购一批办公用品")
    assert r.unit_id == "admin-office", f"got {r.unit_id}"
    assert "admin_specialist" in r.roles

    r2 = router.route("帮我写一份公司公文通知")
    assert r2.unit_id == "admin-office"
    assert "document_archivist" in r2.roles

    r3 = router.route("帮我安排一场年度会议会务")
    assert r3.unit_id == "admin-office"
    assert "meeting_coordinator" in r3.roles

    r4 = router.route("帮我做前台访客接待流程")
    assert r4.unit_id == "admin-office"
    assert "receptionist" in r4.roles


def test_design_visual_route():
    """视觉设计：海报→graphic_designer，UI→ui_designer，插画→illustrator，品牌→brand_designer"""
    reg = Registry()
    router = IntentRouter(reg)

    r = router.route("帮我设计一张活动海报")
    assert r.unit_id == "design-visual", f"got {r.unit_id}"
    assert "graphic_designer" in r.roles

    r2 = router.route("帮我设计一个App的UI界面")
    assert r2.unit_id == "design-visual"
    assert "ui_designer" in r2.roles

    r3 = router.route("帮我画一幅商业插画")
    assert r3.unit_id == "design-visual"
    assert "illustrator" in r3.roles

    r4 = router.route("帮我设计一个品牌logo和VI")
    assert r4.unit_id == "design-visual"
    assert "brand_designer" in r4.roles


def test_existing_industries_stable_after_v4_expansion():
    """扩展不破坏既有行业路由稳定性（回归护栏）"""
    reg = Registry()
    router = IntentRouter(reg)
    stable = {
        "帮我设计一个电商网站": "dongjiagoushi",
        "帮我做一份财务报表": "finance-accounting",
        "帮我写一份租房合同审查": "legal-services",
        "帮我解读体检报告": "healthcare",
        "帮我做一个装修设计方案": "home-design",
    }
    for text, expect in stable.items():
        r = router.route(text)
        assert r.unit_id == expect, f"{text} 期望 {expect}, 实际 {r.unit_id}"


def test_coverage_progressed_to_14():
    """coverage 目标全集同步校准：行业覆盖从 11 提升至 14"""
    ct = CoverageTracker()
    r = ct.compute()
    assert r["covered_industries"] >= 14, f"covered={r['covered_industries']}"
    # 三个新行业确实被判定为已覆盖
    names = {row["name"] for row in r["rows"] if row["status"] == "registered"}
    assert {"人力资源", "行政办公", "视觉设计"} <= names, \
        f"三个高优先级新行业未被判定已覆盖: {names}"


def test_prefix_archive_has_14_units():
    """prefix-archive.json 含全部 14 个行业单元"""
    archive_path = os.path.join(
        os.path.dirname(__file__), "../data/prefix-archive.json")
    assert os.path.exists(archive_path)
    with open(archive_path, "r", encoding="utf-8") as f:
        archive = json.load(f)
    expected = {"dongjiagoushi", "game-dev-unit", "legal-services",
                "content-creation", "data-analytics", "e-commerce",
                "finance-accounting", "marketing", "education-training",
                "healthcare", "home-design",
                "hr-services", "admin-office", "design-visual"}
    assert expected <= set(archive.keys()), \
        f"prefix-archive 缺少: {expected - set(archive.keys())}"


if __name__ == "__main__":
    test_fourteen_industries_registered()
    test_hr_services_route()
    test_admin_office_route()
    test_design_visual_route()
    test_existing_industries_stable_after_v4_expansion()
    test_coverage_progressed_to_14()
    test_prefix_archive_has_14_units()
    print("✅ 行业扩展第四期测试通过")
