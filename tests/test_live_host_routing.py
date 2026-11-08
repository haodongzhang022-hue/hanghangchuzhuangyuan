"""直播语境路由回归（OCI 第 5 轮 4 条行级评论里的 1-3）

复现的错：`直播选品` 在 content-creation.live_host 与 e-commerce.store_manager
两侧都注册成关键词，各得 2.5 分 → 一句回落人工、一句静默错路由到电商。
错的不是分数算错了，而是**同一个组合词被两个单元同时认领**。

修法两头都要：
1. 直播语境的选品还给 live_host（组合词 + 紧邻定语绑定）；
2. 电商保留裸词「选品」——它是「选品 / 帮我选品 / 跨境选品」这类通用诉求的
   唯一入口，删掉它等于把最高频入口砸了（第 10 轮评审的阻塞项）。
歧义由引擎的跨单元认领规则消解，不靠删词。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from hanghang.engine import Registry
from hanghang.engine.router import IntentRouter, _superseded_cjk_hits


def _route(text):
    return IntentRouter().route(text)


def _unit_vocab(unit):
    vocab = list(unit.industry_alias) + list(unit.capability_tags)
    for role in unit.roles:
        vocab.extend(role.get_keywords())
    return vocab


def test_live_product_selection_lands_on_live_host():
    """「帮我做直播选品」必须落到主播，不许回落人工"""
    r = _route("帮我做直播选品")
    assert r.unit_id == "content-creation", f"实际落 {r.unit_id}"
    assert "live_host" in (r.roles or []), r.roles
    assert not getattr(r, "needs_manual", False)


def test_live_context_selection_not_folded_into_ecommerce():
    """带直播语境的选品不得折进电商（这是修复前的静默错路由）"""
    for text in ("帮我设计直播间的选品和话术", "帮我做直播选品", "直播选品怎么做"):
        r = _route(text)
        assert r.unit_id != "e-commerce", f"{text} 被折进电商"


def test_live_intents_pinned_to_live_host():
    """直播意图正向钉住唯一入口（组合词在册，单点词失效也不全丢）"""
    for text in ("帮我写直播话术", "直播脚本怎么写", "直播复盘怎么做",
                 "帮我做直播选品", "帮我设计直播间的选品和话术"):
        r = _route(text)
        assert r.unit_id == "content-creation", f"{text} 落到了 {r.unit_id}"
        assert "live_host" in (r.roles or []), f"{text} 没落 live_host: {r.roles}"


def test_ecommerce_keeps_its_own_selection_intent():
    """拆分不丢电商侧入口：店铺选品/选品上架仍归店长"""
    for text in ("帮我做店铺选品", "电商选品上架", "商品选品怎么做"):
        r = _route(text)
        assert r.unit_id == "e-commerce", f"{text} 落到了 {r.unit_id}"
        assert "store_manager" in (r.roles or []), r.roles


def test_routing_baseline_unchanged():
    """本次改动不许碰既有基线行为"""
    r = _route("架构设计方案")
    assert r.unit_id == "dongjiagoushi" and "architect" in (r.roles or [])
    r = _route("帮我点个外卖")
    assert getattr(r, "needs_manual", False), "外卖仍应回落人工"
    r = _route("既要架构设计又要写代码")
    assert set(r.roles or []) >= {"architect", "developer"}, r.roles


# ---------- 数据层：组合词必须真注册（否则上面几条是靠引擎兜住的） ----------

def test_live_host_has_compound_keywords_in_data():
    """live_host 必须真注册组合词，不能只靠裸「直播」兜底"""
    unit = Registry().get_unit("content-creation")
    host = next(r for r in unit.roles if r.name == "live_host")
    kws = set(host.get_keywords())
    for kw in ("直播间", "直播带货", "直播选品", "直播话术", "直播脚本"):
        assert kw in kws, f"live_host 缺少组合关键词: {kw}"


def test_bare_selection_word_kept_on_ecommerce():
    """裸词「选品」必须留在电商侧（第 10 轮评审：删掉它直接砸掉最高频入口）

    上一版断言「选品不得出现在电商」把回退钉成了"期望行为"——那条不变量本身是错的。
    """
    unit = Registry().get_unit("e-commerce")
    vocab = _unit_vocab(unit)
    assert "选品" in vocab, "电商侧缺裸词「选品」，通用选品诉求会全部回落人工"
    store = next(r for r in unit.roles if r.name == "store_manager")
    assert "选品" in set(store.get_keywords()), store.get_keywords()


def test_bare_selection_intents_land_on_ecommerce():
    """通用选品诉求（未指明渠道）不得回落人工"""
    for text in ("选品", "帮我选品", "选品怎么做", "选品清单",
                 "跨境选品", "亚马逊选品", "供应商选品"):
        r = _route(text)
        assert not getattr(r, "needs_manual", False), f"{text} 回落人工: {r.fallback_reason}"
        assert r.unit_id == "e-commerce", f"{text} 落到了 {r.unit_id}"


def test_select_word_reports_do_not_cross_into_admin_office():
    """「选品报告」不许再被判到 admin-office（靠「报告」蹭分）"""
    r = _route("选品报告")
    assert r.unit_id == "e-commerce", f"实际落 {r.unit_id}"


def test_cross_border_selection_keeps_confidence():
    """「跨境电商选品」的置信度不许腰斩"""
    r = _route("跨境电商选品")
    assert r.unit_id == "e-commerce", r.unit_id
    assert r.confidence >= 0.75, r.confidence


def test_mixed_selection_intent_keeps_ecommerce_hit():
    """「直播选品和选品」：后一处是电商独立再说一遍，不能被主播整词吞掉"""
    router = IntentRouter()
    scores = router._score_units("直播选品和选品", router.registry.all_units())
    ecom = scores.get("e-commerce", {})
    assert "选品" in ecom.get("matched_terms", []), ecom.get("signals")
    live = scores.get("content-creation", {})
    assert any("直播选品" in sig for sig in live.get("signals", [])), live.get("signals")


def test_live_context_with_attributive_joiner_goes_to_live_host():
    """「直播间的选品」这类分写形式整体归主播，不被电商裸词抢走"""
    for text in ("帮我设计直播间的选品和话术", "直播间选品", "直播间的选品话术"):
        r = _route(text)
        assert r.unit_id == "content-creation", f"{text} 落到了 {r.unit_id}"
        assert "live_host" in (r.roles or []), r.roles


def test_attributive_binding_needs_single_joiner():
    """紧邻定语绑定只认 0~1 个定语助词（的/之），且必须紧挨在本词之前"""
    assert _superseded_cjk_hits("直播间的选品", "选品", ["直播间"]) is True
    assert _superseded_cjk_hits("直播间选品", "选品", ["直播间"]) is True
    assert _superseded_cjk_hits("直播话术顺便说下选品", "选品", ["直播话术"]) is False
    assert _superseded_cjk_hits("直播间的好的选品", "选品", ["直播间"]) is False


# ---------- 本方长词已认领时不许向外让位（第 12 轮评审） ----------

def test_own_long_term_blocks_attributive_binding():
    """本单元自己的长词整段盖住这处出现时，不许因为外单元凑巧挨着而让位

    复现（第 12 轮评审给的 6 条，全部「可路由 → 回落人工」）：

        帮我做网页文案
          content-creation: 网页文案(1.5)   ← 自己的长词盖住了「文案」
          dongjiagoushi:    做网页(1.5)     ← 只是挨着「文案」
        旧判定：文案被「做网页」紧邻定语绑定 → 本方让位 → 1.5:1.5 判歧义
    """
    assert _superseded_cjk_hits("帮我做网页文案", "文案", ["做网页"],
                                ["网页文案"]) is False
    # 没有本方长词时照旧让位（这条守住豁免没被写宽）
    assert _superseded_cjk_hits("帮我做网页你好", "你好", ["做网页"], []) is True


def test_attributive_binding_regression_corpus():
    """评审给的 6 条回归语料：必须直连，不许回落人工"""
    cases = {
        "帮我做网页文案": ("content-creation", "copywriter"),
        "帮我搭建网页文案": ("content-creation", "copywriter"),
        "帮我搭建网站文案": ("content-creation", "copywriter"),
        "帮我做网页版权": ("legal-services", "legal_counsel"),
        "帮我搭建网页版权": ("legal-services", "legal_counsel"),
        "帮我搭建网站版权": ("legal-services", "legal_counsel"),
    }
    for text, (unit, role) in cases.items():
        r = _route(text)
        assert not getattr(r, "needs_manual", False), f"{text} 回落人工: {r.fallback_reason}"
        assert r.unit_id == unit, f"{text} 落到了 {r.unit_id}"
        assert role in (r.roles or []), f"{text} 岗位不对: {r.roles}"


# ---------- 引擎层：汉字区间让位规则 ----------

def test_covered_short_word_yields_to_longer_hit():
    """短词每处出现都被外单元长词覆盖 → 让位"""
    assert _superseded_cjk_hits("帮我做直播选品", "选品", ["直播选品"]) is True


def test_independently_appearing_short_word_still_counts():
    """短词有独立出现 → 照常计分（不许误杀）"""
    assert _superseded_cjk_hits("直播间的选品和话术", "选品", ["直播选品"]) is False
    assert _superseded_cjk_hits("直播选品和选品", "选品", ["直播选品"]) is False


def test_supersede_only_applies_to_cjk_terms():
    """英文/数字词边界靠空格，不参与区间让位"""
    assert _superseded_cjk_hits("do SEO audit", "SEO", ["do SEO audit"]) is False


def test_short_word_covered_by_foreign_long_word_does_not_score():
    """被覆盖的短词不给别的单元送分：「核算工资」不该给财务侧送「工资」"""
    router = IntentRouter()
    scores = router._score_units("核算工资", router.registry.all_units())
    finance = scores.get("finance-accounting", {})
    assert "工资" not in finance.get("matched_terms", []), finance.get("fallback")

    r = router.route("核算工资")
    assert not getattr(r, "needs_manual", False), f"仍回落人工: {r.fallback_reason}"
    assert r.unit_id == "hr-services", f"实际落 {r.unit_id}"


def test_supersede_does_not_touch_same_unit_words():
    """本单元内部的长短词口径不变（文案 / 品牌文案 各计一次）"""
    r = _route("帮我写品牌文案")
    assert r.unit_id == "content-creation", f"实际落 {r.unit_id}"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ✅ {name}")
    print("✅ 直播语境路由回归测试通过")
