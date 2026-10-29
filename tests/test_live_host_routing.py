"""直播语境路由回归（OCI 第 5 轮 4 条行级评论里的 1-3）

复现的错：`直播选品` 在 content-creation.live_host 与 e-commerce.store_manager
两侧都注册成关键词，各得 2.5 分 → 一句回落人工、一句静默错路由到电商。
错的不是分数算错了，而是**同一个组合词被两个单元同时认领**。

修法是把"直播语境的选品"还给 live_host（用组合词），电商保留自己的语义
（商品选品 / 选品上架 / 上架 / 店铺），两边都不丢入口。
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


def test_bare_selection_word_not_double_registered():
    """裸词「选品」不得同时出现在直播侧与电商侧（歧义的真正来源）"""
    reg = Registry()
    for uid in ("content-creation", "e-commerce"):
        unit = reg.get_unit(uid)
        assert "选品" not in _unit_vocab(unit), f"{uid} 残留裸词「选品」"


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
