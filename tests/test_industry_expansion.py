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
    # 多维命中时维度不被后匹配覆盖：同时保留 capability(合同审查) 与 role(合同) 两个维度
    assert "role" in legal["hit_kinds"]
    assert "capability" in legal["hit_kinds"]
    # 能力维度命中的标签也应写入实际命中词（评审 warning②）
    assert any("合同审查" in t for t in legal["matched_terms"])

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


# ============================================================
# 评审闭环回归：领域名词 + 开发意图混合场景（critical 路由误判修复）
# ============================================================

def test_software_build_for_domain_not_misrouted():
    """评审 critical 修复：为某业务领域"开发软件/系统/工具/代码/APP"不应判给纯业务域单元。

    "合同/文案/数据分析"等业务名词仅是软件的被构建对象，
    应路由到软件研发单元(dongjiagoushi)而不是 法律/内容/数据分析。
    """
    reg = Registry()
    router = IntentRouter(reg)

    # 合同管理系统 → 软件研发
    r = router.route("帮我开发一个合同管理系统")
    assert r.unit_id == "dongjiagoushi", f"got {r.unit_id}"
    assert r.needs_manual is False
    assert "developer" in r.roles

    # 写合同管理功能的代码 → 软件研发
    r2 = router.route("写一个合同管理功能的代码")
    assert r2.unit_id == "dongjiagoushi", f"got {r2.unit_id}"
    assert "developer" in r2.roles

    # 数据分析工具 → 软件研发
    r3 = router.route("开发一个数据分析工具")
    assert r3.unit_id == "dongjiagoushi", f"got {r3.unit_id}"
    assert "developer" in r3.roles


def test_software_build_app_not_content():
    """构建"文案类APP"属软件工程诉求，不应被误判为内容创作单元"""
    reg = Registry()
    router = IntentRouter(reg)
    r = router.route("做一个文案类APP")
    assert r.unit_id == "dongjiagoushi", f"got {r.unit_id}"
    assert "developer" in r.roles


def test_genuine_domain_work_still_routed_to_domain():
    """修复后，真实业务域作业(审合同/写文案/做报表)仍正确落到对应领域单元"""
    reg = Registry()
    router = IntentRouter(reg)
    # 真实法律作业（不含软件产物名词）
    assert router.route("帮我审一份劳动纠纷的劳动合同").unit_id == "legal-services"
    assert router.route("给新品写一条卖点文案").unit_id == "content-creation"
    assert router.route("做一份本季度销售经营分析报表").unit_id == "data-analytics"
    # 真实数据建模作业
    assert router.route("用历史销售数据训练一个预测模型").unit_id == "data-analytics"


def test_software_build_does_not_break_game_routing():
    """软件产物联合判定不得误伤 游戏研发 路由（共享"开发"词仍按游戏行业信号归游戏）"""
    reg = Registry()
    router = IntentRouter(reg)
    r = router.route("开发一款手机游戏")
    assert r.unit_id == "game-dev-unit", f"got {r.unit_id}"
    # 真跨行业歧义仍回落人工（不因软件产物逻辑误放行）
    r2 = router.route("开发一款游戏需求")
    assert r2.needs_manual is True and r2.is_ambiguous is True


# ============================================================
# 评审闭环回归（第 5 轮）：软件构建改判不得误吞正当业务域作业
# 根因：仅凭"文本含软件产物名词"即改判到软件研发，会把真实业务域作业
#   （写APP推广文案 / 做报表 / 审软件合同 / 做系统性经营分析）静默卷走。
# 修复：产物名词须是句子的"软件构建目标"；若其后仍紧跟业务交付物名词，
#   则产物名词只是修饰/手段，应路由到对应业务域单元，不判软件构建。
# ============================================================

def test_build_override_does_not_swallow_domain_jobs():
    """软件产物联合判定不误吞业务域作业：产物名词仅是修饰/手段时仍归业务域"""
    reg = Registry()
    router = IntentRouter(reg)

    # 内容创作：产物名词(APP/软件)修饰其后的"文案"作业 → 仍归内容创作
    assert router.route("写一篇APP上线推广的营销文案").unit_id == "content-creation",         "APP是文案主题，用户诉求是写文案，不应改判软件"
    assert router.route("写一个APP的功能清单文案").unit_id == "content-creation"
    # 数据分析：工具/平台作为手段/数据来源，用户诉求是做报表/分析 → 归数据分析
    assert router.route("做一份大数据平台的数据看板报表").unit_id == "data-analytics"
    assert router.route("用数据分析工具分析销售数据出报表").unit_id == "data-analytics"
    assert router.route("做一份系统性的经营分析").unit_id == "data-analytics"
    # 法律咨询：审/起草软件相关合同 → 归法律咨询
    assert router.route("帮我审一下这个软件采购合同的风险").unit_id == "legal-services"


def test_build_override_keeps_software_build_intents():
    """产物名词确为软件构建目标（位于句末、其后无业务交付名词）时仍改判软件"""
    reg = Registry()
    router = IntentRouter(reg)
    for text in ("帮我开发一个合同管理系统", "开发一个数据分析工具",
                 "做一个文案类APP", "写一个合同管理功能的代码"):
        r = router.route(text)
        assert r.unit_id == "dongjiagoushi", f"{text} -> {r.unit_id}"
        assert "developer" in r.roles


def test_software_product_brand_copy_surfaces_ambiguity():
    """'给软件产品写品牌文案'横跨软件(产品对象)与内容(写文案)两行业 →
    应回落人工确认，而非被静默改判到软件研发（评审核心关切）"""
    reg = Registry()
    router = IntentRouter(reg)
    r = router.route("给公司的软件产品写品牌文案")
    # 不静默落到软件研发
    assert r.unit_id != "dongjiagoushi" or r.needs_manual,         "软件产品相关文案不应被静默吞到软件研发"
    # 该句确属跨行业歧义时，应回落人工而非自动放行
    if r.needs_manual is False:
        assert r.unit_id == "content-creation", f"got {r.unit_id}"


def test_search_capability_multi_dimension_kept():
    """warning①：多维命中的维度不因后匹配覆盖而丢失（hit_kinds 全量保留）"""
    reg = Registry()
    res = reg.search_capability("合同")
    legal = next(m for m in res if m["unit_id"] == "legal-services")
    assert "industry" in legal["hit_kinds"]
    assert "capability" in legal["hit_kinds"]
    assert "role" in legal["hit_kinds"]


def test_search_capability_capability_term_in_matched():
    """warning②：能力维度命中的标签也写入 matched_terms"""
    reg = Registry()
    res = reg.search_capability("数据分析", mode="capability")
    da = next(m for m in res if m["unit_id"] == "data-analytics")
    assert "数据分析" in da["matched_terms"]


def test_capability_index_tags_all_mapped_for_domain_units():
    """warning③：领域单元的能力标签均映射到承接岗位（无空映射）"""
    reg = Registry()
    index = {i["unit_id"]: i for i in reg.capability_index()}
    for uid in ("legal-services", "content-creation", "data-analytics"):
        for tag, roles in index[uid]["tag_to_roles"].items():
            assert roles, f"{uid} 的能力标签 {tag} 无承接岗位"


# ============================================================
# 评审闭环回归（第 6 轮）：软件构建联合判定收敛
#   critical①：改判须同时满足"存在明确构建动词"，排除副词/所属/法律著作权等
#     通用领域用法 —— "系统的学一下法律""软件产品要怎么推广"等不得被误判软件研发。
#   warning②：软件单元自身正分信号为 0 时不得强制抬置信到 0.6 静默放行。
#   warning③：法律单元补充著作权/登记类承接（"软件著作权登记"归法律）。
# ============================================================

def test_adverb_system_not_routed_to_software_dev():
    """critical①：副词"系统/系统地"用法不得被误判为软件构建到 developer。
    "系统的学一下法律"中"系统"=系统地（副词），应归法律咨询而非软件研发。"""
    reg = Registry()
    router = IntentRouter(reg)
    for text in ("系统的学一下法律", "我要系统的掌握法律知识"):
        r = router.route(text)
        assert r.unit_id != "dongjiagoushi",                f"{text} 副词'系统'被误判为软件研发 -> {r.unit_id}"
        assert "developer" not in r.roles,                  f"{text} 不得落 developer"
        # "系统"在此是"法律"的副词修饰，真实归属法律行业
        assert r.unit_id == "legal-services",               f"{text} -> {r.unit_id}"


def test_software_product_promo_not_silently_auto_dev():
    """critical①："软件产品要怎么推广"是软件营销/内容诉求，不应被当作
    "构建软件"的开发诉求静默路由（不得经软件构建 override 落 developer）。"""
    reg = Registry()
    router = IntentRouter(reg)
    # 不得被改判为 developer 类软件构建作业
    r = router.route("软件产品要怎么推广")
    assert "developer" not in r.roles,                       "软件产品推广诉求不得静默落 developer"


def test_software_copyright_registration_goes_to_legal():
    """warning③："做个软件著作权登记"属法律业务（著作权登记），应归法律咨询，
    而非软件研发；同时不因 override 被改判到软件单元。"""
    reg = Registry()
    router = IntentRouter(reg)
    r = router.route("做个软件著作权登记")
    assert r.unit_id == "legal-services",                    f"著作权登记被误判 -> {r.unit_id}"
    assert r.unit_id != "dongjiagoushi"
    assert not router._is_software_build_intent("做个软件著作权登记")


def test_weak_signal_build_not_silently_auto_route():
    """warning②：软件单元自身无正分信号（仅"做一个软件"弱表达）时不得强制抬置信到
    0.6 静默放行；应显著降置信/回落人工（但仍保留 developer 识别供下游参考）。"""
    reg = Registry()
    router = IntentRouter(reg)
    # "做一个文案类APP" 无具体开发关键词 → 软件单元信号为 0 → 需人工确认
    r = router.route("做一个文案类APP")
    assert r.unit_id == "dongjiagoushi"
    assert r.confidence < 0.6,                                "弱信号软件构建不得抬到 0.6 静默放行"
    # 有真实开发信号（如"开发"）的诉求仍可自动路由
    r2 = router.route("帮我开发一个合同管理系统")
    assert r2.unit_id == "dongjiagoushi"
    assert r2.confidence >= 0.6
    assert r2.needs_manual is False

# ============================================================
# 评审第 7 轮（通过后）非阻塞改进验证
#   info①: prefix-archive.json 已纳入版本控制，含全部5单元
#   info②: data-analytics 补充"分析报告/数据报告"通用业务词提升领域召回
# ============================================================

def test_data_analytics_analysis_report_recall():
    """评审 info②：'做一份软件使用分析报告' 应路由到 data-analytics，
    而非被'软件'别名强信号误导到 软件研发(dongjiagoushi)。"""
    reg = Registry()
    router = IntentRouter(reg)
    r = router.route("做一份软件使用分析报告")
    assert r.unit_id == "data-analytics", f"got {r.unit_id}"
    assert "data_analyst" in r.roles, f"got roles={r.roles}"


def test_data_analytics_data_report_recall():
    """data-analytics 补充 '数据报告' 后，'出一份数据报告' 应被召回"""
    reg = Registry()
    router = IntentRouter(reg)
    r = router.route("帮我出一份数据报告")
    assert r.unit_id == "data-analytics", f"got {r.unit_id}"


def test_data_analytics_generic_terms_no_overreach():
    """通用业务词补充不应过度泛化：'写一份工作报告'/'我需要一份报告'
    等非数据分析场景不应被静默路由到 data-analytics。"""
    reg = Registry()
    router = IntentRouter(reg)
    # 无明确"数据分析/分析报告/数据报告"等业务词时不应自动路由到 data-analytics
    for text in ("写一份工作报告", "我需要一份报告", "写报告", "帮我做一份项目进度报告"):
        r = router.route(text)
        assert r.unit_id != "data-analytics" or r.needs_manual, \
            f"{text} 不应被静默路由到 data-analytics"


def test_prefix_archive_file_in_git():
    """评审 info①：data/prefix-archive.json 已纳入版本控制，含全部5个单元"""
    archive_path = os.path.join(
        os.path.dirname(__file__), "../data/prefix-archive.json")
    assert os.path.exists(archive_path), \
        f"prefix-archive.json 不存在: {archive_path}"
    import json
    with open(archive_path, "r", encoding="utf-8") as f:
        archive = json.load(f)
    expected_units = {"dongjiagoushi", "game-dev-unit", "legal-services",
                      "content-creation", "data-analytics"}
    assert expected_units <= set(archive.keys()), \
        f"prefix-archive.json 缺少单元: {expected_units - set(archive.keys())}"


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
    test_software_build_for_domain_not_misrouted()
    test_software_build_app_not_content()
    test_genuine_domain_work_still_routed_to_domain()
    test_software_build_does_not_break_game_routing()
    test_build_override_does_not_swallow_domain_jobs()
    test_build_override_keeps_software_build_intents()
    test_software_product_brand_copy_surfaces_ambiguity()
    test_search_capability_multi_dimension_kept()
    test_search_capability_capability_term_in_matched()
    test_capability_index_tags_all_mapped_for_domain_units()
    test_adverb_system_not_routed_to_software_dev()
    test_software_product_promo_not_silently_auto_dev()
    test_software_copyright_registration_goes_to_legal()
    test_weak_signal_build_not_silently_auto_route()
    test_data_analytics_analysis_report_recall()
    test_data_analytics_data_report_recall()
    test_data_analytics_generic_terms_no_overreach()
    test_prefix_archive_file_in_git()
    print("✅ 行业扩展 + M8 索引增强 + 评审回归测试通过")
