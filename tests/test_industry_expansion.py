"""行业横向扩展测试：新增行业单元 + M8 能力索引增强

本轮开发要点：
1. 把"行行出状元"从 2 个行业扩展到 5 个（新增 法律咨询/内容创作/数据分析），
   验证纯数据驱动下新增行业无需改代码即可被路由/复合/索引。
2. 增强 M8：从简单"哪个单元有关键词"升级为多维检索 search_capability，
   并新增全量能力索引导出 capability_index（供上层编排/可视化聚合）。
3. 确保扩展不破坏原有行业路由稳定性（泛化词/歧义回落不因新增词而误判）。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from hanghang.engine import (
    Registry, IntentRouter, CompositePlanner, HandoffBus,
)

# ============================================================
# 一、新行业单元注册与路由
# ============================================================

def test_five_industries_registered():
    """5 个行业单元均已注册（软件/游戏/法律/内容创作/数据分析）"""
    reg = Registry()
    ids = {u.unit_id for u in reg.all_units()}
    assert {"dongjiagoushi", "game-dev-unit", "legal-services",
            "content-creation", "data-analytics"} <= ids


def test_legal_consultant_route():
    """法律咨询：合同审查→合同顾问，反垄断合规→合规顾问"""
    reg = Registry()
    router = IntentRouter(reg)

    r = router.route("帮我审一份劳动纠纷的劳动合同")
    assert r.unit_id == "legal-services", f"got {r.unit_id}"
    assert "contract_advisor" in r.roles

    r2 = router.route("公司并购前要做反垄断合规审查")
    assert r2.unit_id == "legal-services"
    assert "compliance_advisor" in r2.roles


def test_legal_composite_route():
    """法律咨询同行业复合：律师+合同顾问同一 session 并装"""
    reg = Registry()
    planner = CompositePlanner(reg)
    plan = planner.plan("既要打官司应诉又要审查买卖合同条款")
    assert plan["mode"] == "composite", f"got mode={plan.get('mode')}"
    assert "legal_counsel" in plan["roles"]
    assert "contract_advisor" in plan["roles"]
    assert "session_prefix_set" in plan


def test_content_creation_route():
    """内容创作：文案/新媒体/编辑三类岗位路由"""
    reg = Registry()
    router = IntentRouter(reg)

    r = router.route("给新品写一条卖点文案")
    assert r.unit_id == "content-creation", f"got {r.unit_id}"
    assert "copywriter" in r.roles

    r2 = router.route("运营一个生活类公众号")
    assert r2.unit_id == "content-creation"
    assert "media_operator" in r2.roles

    r3 = router.route("帮忙审校润色一篇发布稿")
    assert r3.unit_id == "content-creation"
    assert "content_editor" in r3.roles


def test_data_analytics_route():
    """数据分析：数分/数科/BI 三类岗位路由"""
    reg = Registry()
    router = IntentRouter(reg)

    r = router.route("做一份本季度销售经营分析报表")
    assert r.unit_id == "data-analytics", f"got {r.unit_id}"
    assert "data_analyst" in r.roles

    r2 = router.route("用历史销售数据训练一个预测模型")
    assert r2.unit_id == "data-analytics"
    assert "data_scientist" in r2.roles


# ============================================================
# 二、新增行业的跨行业交接（M5）
# ============================================================

def test_cross_unit_software_to_legal():
    """跨行业交接：软件研发(系统) → 法律(合规)，可自动创建交接卡"""
    import tempfile
    reg = Registry()
    router = IntentRouter(reg)

    # 明确跨行业独立信号：法律合规 + 软件架构设计
    cands = router.cross_unit_candidates("做一个系统合规架构方案并出法律意见")
    assert len(cands) >= 2
    assert "legal-services" in cands
    assert "dongjiagoushi" in cands

    with tempfile.TemporaryDirectory() as tmpdir:
        bus = HandoffBus(data_dir=tmpdir)
        planner = CompositePlanner(reg, handoff_bus=bus)
        plan = planner.plan_cross_unit(
            "做一个系统合规架构方案并出法律意见",
            source_unit_id="dongjiagoushi",
            target_unit_id="legal-services",
        )
        assert plan["mode"] == "cross_unit_handoff"
        assert plan["handoff_card_id"] is not None


# ============================================================
# 三、M8 能力索引增强
# ============================================================

def test_search_capability_any_dimension():
    """M8 any 维度：按关键词找承接单元/岗位/能力"""
    reg = Registry()

    # "合同" 应命中 legal-services 的 contract_advisor
    res = reg.search_capability("合同")
    assert any(m["unit_id"] == "legal-services" for m in res)
    legal = next(m for m in res if m["unit_id"] == "legal-services")
    assert "contract_advisor" in legal["hit_roles"]
    assert legal["hit_kind"] in ("role", "capability")

    # "架构" 命中 dongjiagoushi
    arch = reg.search_capability("架构")
    assert any(m["unit_id"] == "dongjiagoushi" for m in arch)


def test_search_capability_mode_filter():
    """M8 role 维度仅按岗位关键词命中"""
    reg = Registry()

    # role 维度下 "公众号" 命中 media_operator
    res = reg.search_capability("公众号", mode="role")
    media = [m for m in res if m["unit_id"] == "content-creation"]
    assert media and "media_operator" in media[0]["hit_roles"]

    # role 维度下行业别名不再单独命中：如"法律"若仅在行业别名，不返回(除非命中岗位词)
    # 但 legal 岗位含"法律咨询"关键词，故仍会命中，验证其属于岗位维度
    res2 = reg.search_capability("法律咨询", mode="role")
    assert any(m["unit_id"] == "legal-services" for m in res2)


def test_capability_index_full_export():
    """M8 capability_index 全量导出，含能力→承接岗位映射"""
    reg = Registry()
    index = reg.capability_index()
    assert len(index) == len(reg.all_units())

    legal = next(i for i in index if i["unit_id"] == "legal-services")
    # 能力标签"合同审查"应映射到合同顾问岗位
    assert "合同审查" in legal["capability_tags"]
    # 每个单元都应带 entry_ref 字段（可为空=本仓集中待回填）
    assert "entry_ref" in legal


def test_capability_index_present_route_address():
    """能力索引导出可路由入口：有源仓的单元带 entry_ref，集中本仓的可为空"""
    reg = Registry()
    index = reg.capability_index()
    sw = next(i for i in index if i["unit_id"] == "dongjiagoushi")
    assert sw["entry_ref"]  # 软件研发有源仓地址
    legal = next(i for i in index if i["unit_id"] == "legal-services")
    assert legal["entry_ref"] == ""  # 本仓集中待回填


# ============================================================
# 四、扩展不破坏原有行业路由（回归护栏）
# ============================================================

def test_existing_industries_stable_after_expansion():
    """新增行业后，原有软件/游戏路由不因新词产生误判"""
    reg = Registry()
    router = IntentRouter(reg)

    # 架构方案仍归软件
    r = router.route("设计一个高并发系统的架构方案")
    assert r.unit_id == "dongjiagoushi"
    assert "architect" in r.roles

    # 游戏关卡仍归游戏
    r2 = router.route("做一版副本的关卡设计")
    assert r2.unit_id == "game-dev-unit"
    assert "level_designer" in r2.roles

    # 泛化词伪歧义仍稳定回落软件(不因新增单元引入新歧义)
    r3 = router.route("开发一个网页应用")
    assert r3.needs_manual is False
    assert r3.unit_id == "dongjiagoushi"

    # 真跨行业歧义仍触发人工(不因扩展误放行)
    r4 = router.route("开发一款游戏需求")
    assert r4.needs_manual is True
    assert r4.is_ambiguous is True


def test_manual_fallback_unaffected():
    """无关意图(外卖)仍回落人工，不被新行业误吞"""
    reg = Registry()
    router = IntentRouter(reg)
    r = router.route("帮我点个外卖")
    assert r.needs_manual is True


if __name__ == "__main__":
    test_five_industries_registered()
    test_legal_consultant_route()
    test_legal_composite_route()
    test_content_creation_route()
    test_data_analytics_route()
    test_cross_unit_software_to_legal()
    test_search_capability_any_dimension()
    test_search_capability_mode_filter()
    test_capability_index_full_export()
    test_capability_index_present_route_address()
    test_existing_industries_stable_after_expansion()
    test_manual_fallback_unaffected()
    print("✅ 行业扩展 + M8 索引增强测试通过")
