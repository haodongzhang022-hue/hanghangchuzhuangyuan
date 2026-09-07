"""dongjiagoushi 走 M1 自动路由外挂验证（T3）

证明首行业单元 dongjiagoushi（软件研发·架构团队）能被通用能力层 M1
意图路由自动识别并落地，作为其它行业单元接入的范式回归护栏。

覆盖：
- R1 单直连 → architect
- R2 复合装配(M6) → product+architect+developer + 稳定前缀集
- R3 软件构建意图联合判定 → developer（制品词不误吞业务域）
- R4 复合短语编码 → developer
- M3 稳定前缀档案与注册表一致
- 负向：网页业务作业不误路由到 dongjiagoushi
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from hanghang.engine import Registry, IntentRouter, CompositePlanner, PrefixArchive


def setup():
    reg = Registry()
    prefixes = PrefixArchive()
    for u in reg.all_units():
        prefixes.register_unit(u)
    return reg, prefixes


def test_r1_direct_architect():
    """R1 单直连：软件架构方案 → dongjiagoushi@architect"""
    reg, _ = setup()
    r = IntentRouter(reg).route("帮我做一套软件架构设计方案")
    assert r.unit_id == "dongjiagoushi"
    assert r.roles == ["architect"], f"got {r.roles}"
    assert r.needs_manual is False


def test_r2_composite_product_architect_dev():
    """R2 复合装配：产品+架构+开发同session"""
    reg, prefixes = setup()
    plan = CompositePlanner(reg).plan("既要架构设计又要开发编码，还要做产品规划")
    assert plan["mode"] == "composite"
    assert plan["unit_id"] == "dongjiagoushi"
    assert plan["roles"] == ["product", "architect", "developer"], f"got {plan['roles']}"
    # 稳定前缀集 = 命中岗位并集
    assert set(plan["session_prefix_set"]) == {"[产品]", "[架构]", "[开发]"}
    # 执行顺序 product → architect → developer
    assert plan["execution_order"] == ["product", "architect", "developer"]


def test_r3_software_build_to_developer():
    """R3 软件构建意图：制品词(网站) → developer 而非误吞业务域"""
    reg, _ = setup()
    r = IntentRouter(reg).route("帮我搭个前端网站")
    assert r.unit_id == "dongjiagoushi"
    assert r.roles == ["developer"], f"got {r.roles}"


def test_r4_composite_phrase_dev():
    """R4 设计并编码工具 → developer"""
    reg, _ = setup()
    r = IntentRouter(reg).route("帮我设计并编码一个数据分析工具")
    assert r.unit_id == "dongjiagoushi"
    assert r.roles == ["developer"]


def test_m3_prefix_archive_consistent():
    """M3 前缀档案：dongjiagoushi 前缀集稳定且与注册一致"""
    reg, prefixes = setup()
    unit = reg.get_unit("dongjiagoushi")
    assert unit is not None
    prefixes_u = prefixes.get_unit_prefixes("dongjiagoushi")
    # 档案含秘书/架构/开发/评审/产品五坑位
    for marker in ["[秘书]", "[架构]", "[开发]", "[评审]", "[产品]"]:
        assert marker in prefixes_u, f"缺稳定前缀 {marker}"


def test_negative_web_business_not_dongjiagoushi():
    """负向护栏：网页业务作业不误路由 dongjiagoushi"""
    reg, _ = setup()
    router = IntentRouter(reg)
    for intent in ["帮我的网站做SEO优化和推广",
                   "帮我翻译这个网页内容",
                   "帮我分析一下网站运营数据"]:
        r = router.route(intent)
        assert r.unit_id != "dongjiagoushi", (
            f"业务域作业被误吞到 dongjiagoushi: {intent}"
        )


if __name__ == "__main__":
    test_r1_direct_architect()
    test_r2_composite_product_architect_dev()
    test_r3_software_build_to_developer()
    test_r4_composite_phrase_dev()
    test_m3_prefix_archive_consistent()
    test_negative_web_business_not_dongjiagoushi()
    print("✅ dongjiagoushi M1 自动路由外挂验证通过")
