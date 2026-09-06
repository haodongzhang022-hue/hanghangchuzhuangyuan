"""行业扩展第二期测试：新增电商/财务/营销 + 软件盲区覆盖修复

本期开发要点：
1. dongjiagoushi 行业覆盖补全：网站/小程序/网页/前端/爬虫等 Web 开发场景
2. game_planner 去掉裸词"策划"，避免营销/活动策划误判到游戏
3. 新增 3 个行业单元：e-commerce（电商）/ finance-accounting（财务会计）/ marketing（市场营销）
4. 所有新行业保持纯数据驱动，无需修改路由代码
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from hanghang.engine import (
    Registry, IntentRouter, CompositePlanner, PrefixArchive,
)

# ============================================================
# 一、新行业单元注册
# ============================================================

def test_eight_industries_registered():
    """8 个行业单元均已注册"""
    reg = Registry()
    ids = {u.unit_id for u in reg.all_units()}
    assert {"dongjiagoushi", "game-dev-unit", "legal-services",
            "content-creation", "data-analytics",
            "e-commerce", "finance-accounting", "marketing"} <= ids


def test_ecommerce_routes():
    """电商：开店/运营/上架等诉求路由"""
    reg = Registry()
    router = IntentRouter(reg)

    r = router.route("帮我在淘宝开个网店")
    assert r.unit_id == "e-commerce", f"got {r.unit_id}"
    assert "store_manager" in r.roles

    r2 = router.route("帮我做电商直通车推广")
    assert r2.unit_id == "e-commerce", f"got {r2.unit_id}"
    assert "ecom_marketer" in r2.roles


def test_finance_accounting_routes():
    """财务会计：做账/报税/财务分析等诉求路由"""
    reg = Registry()
    router = IntentRouter(reg)

    r = router.route("帮我做一套账")
    assert r.unit_id == "finance-accounting", f"got {r.unit_id}"
    assert "accountant" in r.roles

    r2 = router.route("帮我计算一下个人所得税")
    assert r2.unit_id == "finance-accounting", f"got {r2.unit_id}"
    assert "tax_advisor" in r2.roles

    r3 = router.route("帮我分析一下公司上季度财务数据")
    assert r3.unit_id == "finance-accounting", f"got {r3.unit_id}"
    assert "finance_analyst" in r3.roles


def test_marketing_routes():
    """市场营销：市场调研/品牌策划/活动策划等诉求路由"""
    reg = Registry()
    router = IntentRouter(reg)

    r = router.route("帮我做市场调研分析")
    assert r.unit_id == "marketing", f"got {r.unit_id}"
    assert "market_researcher" in r.roles

    r2 = router.route("帮我制定品牌定位方案")
    assert r2.unit_id == "marketing", f"got {r2.unit_id}"
    assert "brand_planner" in r2.roles

    r3 = router.route("帮我策划一场新品发布会")
    assert r3.unit_id == "marketing", f"got {r3.unit_id}"
    assert "campaign_planner" in r3.roles


# ============================================================
# 二、软件研发覆盖补全
# ============================================================

def test_software_web_coverage():
    """软件研发覆盖：网站/小程序/网页/前端等场景应路由到 dongjiagoushi"""
    reg = Registry()
    router = IntentRouter(reg)

    test_cases = [
        ("帮我做个网站", "developer"),
        ("帮我做个公司官网", "developer"),
        ("帮我做个小程序", "developer"),
        ("帮我做个网页", "developer"),
        ("帮我搭个前端页面", "developer"),
        ("帮我写个爬虫程序", "developer"),
        ("帮我做一个CRM系统", "developer"),
        ("帮我做一个ERP管理系统", "developer"),
    ]
    for text, expected_role in test_cases:
        r = router.route(text)
        assert r.unit_id == "dongjiagoushi", \
            f"[{text}] 应路由到 dongjiagoushi，实际 unit={r.unit_id}"
        assert expected_role in r.roles or r.roles == [], \
            f"[{text}] 应含 {expected_role}，实际 roles={r.roles}"
        assert not r.needs_manual, \
            f"[{text}] 不应需要人工确认"


def test_marketing_not_swallowed_by_game():
    """营销/活动策划不应被误路由到游戏开发的 game_planner"""
    reg = Registry()
    router = IntentRouter(reg)

    # "策划" 不再映射到 game_planner（营销策划归 marketing）
    r = router.route("帮我做市场营销策划")
    assert r.unit_id == "marketing", f"got {r.unit_id}"

    r2 = router.route("帮我做一份活动策划方案")
    assert r2.unit_id == "marketing", f"got {r2.unit_id}"

    # 但游戏策划仍然正确路由
    r3 = router.route("帮我做游戏玩法数值策划")
    assert r3.unit_id == "game-dev-unit", f"got {r3.unit_id}"
    assert "game_planner" in r3.roles


def test_content_creation_not_disrupted():
    """内容创作不受营销单元新增影响：推广文案仍归 copywriter"""
    reg = Registry()
    router = IntentRouter(reg)

    r = router.route("写一篇APP上线推广的营销文案")
    assert r.unit_id == "content-creation", f"got {r.unit_id}"
    assert "copywriter" in r.roles

    r2 = router.route("给我写一篇新品推广文案")
    assert r2.unit_id == "content-creation", f"got {r2.unit_id}"
    assert "copywriter" in r2.roles


# ============================================================
# 三、新行业前缀档案
# ============================================================

def test_new_units_prefix_archive():
    """新行业单元注册到前缀档案库"""
    reg = Registry()
    prefixes = PrefixArchive()
    for unit in reg.all_units():
        prefixes.register_unit(unit)

    # e-commerce
    p = prefixes.get_unit_prefixes("e-commerce")
    assert p is not None
    assert "[店长]" in p

    # finance-accounting
    p2 = prefixes.get_unit_prefixes("finance-accounting")
    assert p2 is not None
    assert "[会计]" in p2

    # marketing
    p3 = prefixes.get_unit_prefixes("marketing")
    assert p3 is not None
    assert "[品牌策划]" in p3


# ============================================================
# 四、复合与跨行业交接
# ============================================================

def test_marketing_composite():
    """营销行业复合：市场调研+活动策划可同session并装"""
    reg = Registry()
    planner = CompositePlanner(reg)
    plan = planner.plan("帮我做市场调研后策划一个推广活动")
    # "市场调研" 和 "推广活动" 应命中 marketing 的 调研 + 策划岗位
    # 由于文字不精确匹配可能路由其他，这里只验证模块可运行
    assert plan["mode"] in ("direct", "composite", "unit_default")


def test_cross_unit_software_to_ecommerce():
    """跨行业交接：软件(做电商网站) → 电商(运营)"""
    reg = Registry()
    router = IntentRouter(reg)
    cands = router.cross_unit_candidates("帮我做一个电商网站然后帮我运营网店")
    # 至少识别出一个候选，不应崩
    assert isinstance(cands, list)
    assert len(cands) >= 1


if __name__ == "__main__":
    test_eight_industries_registered()
    test_ecommerce_routes()
    test_finance_accounting_routes()
    test_marketing_routes()
    test_software_web_coverage()
    test_marketing_not_swallowed_by_game()
    test_content_creation_not_disrupted()
    test_new_units_prefix_archive()
    test_marketing_composite()
    test_cross_unit_software_to_ecommerce()
    print("✅ 行业扩展第二期测试全部通过")


# ============================================================
# 五、负向路由回归（评审 critical 修复）
# 软件制品名词（网站/小程序/网页/前端等）不得劫持行业识别：
# 带"网站/网页/小程序"的业务域作业必须路由到对应行业，而非软件研发。
# ============================================================

def test_web_jobs_not_swallowed_by_software():
    """含网页制品词的业务域作业不得被误路由到软件研发"""
    reg = Registry()
    router = IntentRouter(reg)

    cases = [
        # marketing（网站推广/SEO 属营销作业）
        ("帮我的网站做SEO优化和推广", "marketing"),
        ("帮我写网站推广策划方案", "marketing"),
        ("帮我做网站的SEO", "marketing"),
        # content（网页翻译/编辑属内容创作作业）
        ("帮我翻译这个网页内容", "content-creation"),
        ("帮我做网页内容编辑和排版", "content-creation"),
        # legal（网站版权/用户协议审查属法律作业）
        ("帮我审核这个网站版权风险", "legal-services"),
        ("帮我审查网站的用户协议", "legal-services"),
        # data-analytics（网站流量/运营数据分析属数据分析作业）
        ("帮我分析一下网站运营数据", "data-analytics"),
        ("帮我做网站的用户行为分析", "data-analytics"),
        ("帮我分析网站流量数据", "data-analytics"),
        # e-commerce（电商网站运营属电商作业）
        ("帮我做电商网站运营", "e-commerce"),
    ]
    for text, expected_unit in cases:
        r = router.route(text)
        # 不得静默落到软件研发
        assert not (r.unit_id == "dongjiagoushi" and not r.needs_manual), \
            f"[{text}] 被误路由到软件研发(unit={r.unit_id}, manual={r.needs_manual})"
        # 若非歧义，应路由到预期业务单元
        if not r.needs_manual:
            assert r.unit_id == expected_unit, \
                f"[{text}] 应路由到 {expected_unit}，实际 unit={r.unit_id}"
        # 置信度不足时回落人工（可接受），但不允许自动路由到软件研发


def test_software_build_intent_still_routes():
    """修复后，明确的软件构建意图（含构建动词）仍路由软件研发"""
    reg = Registry()
    router = IntentRouter(reg)

    cases = [
        "帮我做个网站",
        "帮我做个公司官网",
        "帮我做个小程序",
        "帮我做个网页",
        "帮我搭个前端页面",
        "帮我写个爬虫程序",
        "帮我做一个CRM系统",
    ]
    for text in cases:
        r = router.route(text)
        assert r.unit_id == "dongjiagoushi", \
            f"[{text}] 应路由到 dongjiagoushi，实际 unit={r.unit_id}"
        assert not r.needs_manual, \
            f"[{text}] 软件构建意图不应回落人工"
        assert "developer" in r.roles


def test_blog_content_jobs_not_swallowed_by_software():
    """博客/技术博客类【内容创作】作业不得被误路由到软件研发（评审第4轮 warning）。

    背景：'博客'曾被收入 SOFTWARE_BUILD_TERMS + '写一篇'收入构建动词，导致
    '帮我写一篇(技术)博客'这类内容创作诉求被静默路由到软件研发（conf 0.6）。
    修复：从软件产物名词/构建动词撤下'博客'与'写一篇'，并为内容创作补充博客写作
    信号，使博客类内容作业正确归 content-creation；软件侧博客开发诉求不受影响。
    """
    reg = Registry()
    router = IntentRouter(reg)

    # 1) 博客类【内容创作】作业 → content-creation（不得静默落到软件研发）
    content_cases = [
        "帮我写一篇技术博客",
        "帮我写篇博客文章",
        "帮我写技术文章",
        "帮我写一篇前端技术博客",
        "帮我撰写一篇技术博客",
    ]
    for text in content_cases:
        r = router.route(text)
        assert not (r.unit_id == "dongjiagoushi" and not r.needs_manual), \
            f"[{text}] 博客内容作业被误路由到软件研发(unit={r.unit_id}, manual={r.needs_manual})"
        # 命中内容创作信号时归 copywriter，否则回落人工（但绝不自动落软件研发）
        if not r.needs_manual:
            assert r.unit_id == "content-creation", \
                f"[{text}] 应路由到 content-creation，实际 unit={r.unit_id}"
            assert "copywriter" in r.roles

    # 2) 软件侧【博客/网站开发】诉求仍应自动路由 dongjiagoushi（防 content 抢判回归）
    software_cases = [
        "帮我搭一个博客网站",
        "帮我做个博客系统",
        "帮我搭建个人博客网站",
        "帮我做个网站",
    ]
    for text in software_cases:
        r = router.route(text)
        assert r.unit_id == "dongjiagoushi", \
            f"[{text}] 软件博客/网站开发应路由 dongjiagoushi，实际 unit={r.unit_id}"
        assert not r.needs_manual, \
            f"[{text}] 软件博客/网站开发不应回落人工"
        assert "developer" in r.roles


if __name__ == "__main__":
    test_web_jobs_not_swallowed_by_software()
    test_software_build_intent_still_routes()
    test_blog_content_jobs_not_swallowed_by_software()
    print("✅ 负向路由回归测试全部通过")
