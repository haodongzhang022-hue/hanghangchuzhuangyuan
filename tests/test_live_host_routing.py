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

from hanghang.engine.router import IntentRouter


def _route(text):
    return IntentRouter().route(text)


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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ✅ {name}")
    print("✅ 直播语境路由回归测试通过")
