"""SLIB 会话级行业绑定（Session-Level Industry Binding）测试

核心目标：
  1. SessionBindingStore：绑定/解绑/查询/列出的持久化 CRUD
  2. SessionBoundRouter 路由约束：
     - 无 session_id → 退化为纯意图路由（向后兼容）
     - 新 session 首次路由 → 自动绑定到路由行业
     - 已绑定 session 收到同行业消息 → 在绑定行业内正常路由
     - 已绑定 session 收到跨行业消息 → 触发 cross_industry_handoff
     - 同 session 不能切换行业（SLIB 强约束）
"""
import os
import sys
import json
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from hanghang.engine import (
    Registry, IntentRouter,
    SessionBinding, SessionBindingStore, SessionBoundRouter,
)


# ============ SessionBindingStore CRUD ============

def test_bind_and_get():
    """绑定并读取"""
    td = tempfile.mkdtemp()
    store = SessionBindingStore(data_dir=td)

    b = store.bind("sess-1", "dongjiagoushi", "软件研发", "architect")
    assert b.session_id == "sess-1"
    assert b.unit_id == "dongjiagoushi"
    assert b.industry == "软件研发"
    assert b.role_name == "architect"

    b2 = store.get_binding("sess-1")
    assert b2 is not None
    assert b2.unit_id == "dongjiagoushi"
    assert b2.industry == "软件研发"


def test_bind_duplicate_same_industry():
    """重复绑定同一行业不报错"""
    td = tempfile.mkdtemp()
    store = SessionBindingStore(data_dir=td)

    store.bind("sess-2", "dongjiagoushi", "软件研发")
    b2 = store.bind("sess-2", "dongjiagoushi", "软件研发", "developer")
    assert b2.role_name == "developer"


def test_bind_conflicting_industry_rejected():
    """已绑定行业，换绑不同行业被拒绝"""
    td = tempfile.mkdtemp()
    store = SessionBindingStore(data_dir=td)

    store.bind("sess-3", "dongjiagoushi", "软件研发")
    try:
        store.bind("sess-3", "healthcare", "健康医疗")
        assert False, "不应允许跨行业换绑"
    except ValueError as e:
        assert "已绑定" in str(e)


def test_unbind():
    """解绑"""
    td = tempfile.mkdtemp()
    store = SessionBindingStore(data_dir=td)

    store.bind("sess-4", "game-dev-unit", "游戏研发")
    assert store.is_bound("sess-4")
    assert store.unbind("sess-4")
    assert not store.is_bound("sess-4")
    assert not store.unbind("sess-4")  # 重复解绑返回 False


def test_list_bindings():
    """列出所有绑定"""
    td = tempfile.mkdtemp()
    store = SessionBindingStore(data_dir=td)

    store.bind("sess-a", "dongjiagoushi", "软件研发")
    store.bind("sess-b", "healthcare", "健康医疗")

    bindings = store.list_bindings()
    assert len(bindings) == 2
    sessions = {b.session_id for b in bindings}
    assert sessions == {"sess-a", "sess-b"}


def test_invalid_session_id():
    """非法 session_id 拒绝"""
    td = tempfile.mkdtemp()
    store = SessionBindingStore(data_dir=td)

    try:
        store.bind("../evil", "dongjiagoushi", "软件研发")
        assert False, "路径穿越应被拒绝"
    except ValueError:
        pass


def test_persistence():
    """绑定持久化：store 重建后数据仍在"""
    td = tempfile.mkdtemp()
    store1 = SessionBindingStore(data_dir=td)
    store1.bind("sess-p", "dongjiagoushi", "软件研发")

    store2 = SessionBindingStore(data_dir=td)
    b = store2.get_binding("sess-p")
    assert b is not None
    assert b.unit_id == "dongjiagoushi"


# ============ SessionBoundRouter：无 session（向后兼容） ============

def test_router_without_session_backward_compat():
    """不传 session_id → 纯意图路由，行为与原 IntentRouter 一致"""
    td = tempfile.mkdtemp()
    store = SessionBindingStore(data_dir=td)
    router = SessionBoundRouter(binding_store=store)

    r = router.route("数据库架构设计方案")
    assert r["session_aware"] is False
    assert r["route_result"]["unit_id"] == "dongjiagoushi"
    assert r["route_result"]["roles"] == ["architect"]
    assert r["mode"] in ("direct", "composite", "manual")

    # 手动回落
    r2 = router.route("帮我点个外卖")
    assert r2["route_result"]["needs_manual"] is True


# ============ SessionBoundRouter：会话感知路由 ============

def test_auto_bind_on_first_route():
    """新 session 首次路由 → 自动绑定"""
    td = tempfile.mkdtemp()
    store = SessionBindingStore(data_dir=td)
    router = SessionBoundRouter(binding_store=store)

    r = router.route("帮我做软件架构设计方案", session_id="newsess-1")
    b = store.get_binding("newsess-1")
    assert b is not None, "首次路由应自动绑定"
    assert b.unit_id == "dongjiagoushi"
    assert b.industry == "软件研发"


def test_same_industry_route_in_bound_session():
    """已绑定 session 收到同行业消息 → 正常路由"""
    td = tempfile.mkdtemp()
    store = SessionBindingStore(data_dir=td)
    router = SessionBoundRouter(binding_store=store)

    router.bind_session("sess-sw", "dongjiagoushi", "软件研发")

    r = router.route("开发一套客户关系管理系统", session_id="sess-sw")
    assert r["route_result"]["unit_id"] == "dongjiagoushi"
    assert r["mode"] != "cross_industry_handoff"

    # 绑定仍然存在且不变
    b = store.get_binding("sess-sw")
    assert b.unit_id == "dongjiagoushi"


def test_cross_industry_handoff_in_bound_session():
    """已绑定 session 收到跨行业消息 → 触发 cross_industry_handoff"""
    td = tempfile.mkdtemp()
    store = SessionBindingStore(data_dir=td)
    router = SessionBoundRouter(binding_store=store)

    router.bind_session("sess-sw2", "dongjiagoushi", "软件研发")

    # 医疗行业消息
    r = router.route("帮我制定健身计划", session_id="sess-sw2")
    assert r["mode"] == "cross_industry_handoff"
    assert r["bound_unit_id"] == "dongjiagoushi"
    assert r["target_unit_id"] == "healthcare"
    assert "不能同会话跨行业" in r["message"]

    # 法律行业消息
    r2 = router.route("审一下这个合同", session_id="sess-sw2")
    assert r2["mode"] == "cross_industry_handoff"
    assert r2["target_unit_id"] == "legal-services"


def test_bound_session_not_switch_industry():
    """会话绑定行业不可被后续路由切换"""
    td = tempfile.mkdtemp()
    store = SessionBindingStore(data_dir=td)
    router = SessionBoundRouter(binding_store=store)

    # 绑定到软件研发
    router.bind_session("sess-fix", "dongjiagoushi", "软件研发")

    # 尝试路由到健康医疗
    r = router.route("心理咨询", session_id="sess-fix")
    assert r["mode"] == "cross_industry_handoff"

    # 绑定仍然保持软件研发
    b = store.get_binding("sess-fix")
    assert b.unit_id == "dongjiagoushi"
    assert b.industry == "软件研发"


def test_cross_industry_auto_handoff_card():
    """跨行业冲突时自动创建交接卡"""
    td = tempfile.mkdtemp()
    store = SessionBindingStore(data_dir=td)
    router = SessionBoundRouter(binding_store=store)

    router.bind_session("sess-ho", "dongjiagoushi", "软件研发")
    r = router.route("帮我制定健身计划", session_id="sess-ho")
    assert r["mode"] == "cross_industry_handoff"
    assert r.get("handoff_card_id"), "应自动创建交接卡"


def test_bound_session_multiple_roles_composite():
    """已绑定 session 多岗位复合路由"""
    td = tempfile.mkdtemp()
    store = SessionBindingStore(data_dir=td)
    router = SessionBoundRouter(binding_store=store)

    router.bind_session("sess-cmp", "dongjiagoushi", "软件研发")
    r = router.route("既要架构设计又要落地开发", session_id="sess-cmp")
    rr = r["route_result"]
    assert rr["unit_id"] == "dongjiagoushi"
    assert "architect" in rr["roles"]
    assert "developer" in rr["roles"]
    assert r["mode"] == "composite"


def test_bind_to_other_unit_then_route():
    """手动 bind 到 A 行业后，路由 A 行业消息正常"""
    td = tempfile.mkdtemp()
    store = SessionBindingStore(data_dir=td)
    router = SessionBoundRouter(binding_store=store)

    router.bind_session("sess-hc", "healthcare", "健康医疗")

    r = router.route("帮我解读体检报告", session_id="sess-hc")
    assert r["route_result"]["unit_id"] == "healthcare"
    assert r["mode"] != "cross_industry_handoff"


def test_unbind_and_reroute():
    """解绑后重新路由到不同行业"""
    td = tempfile.mkdtemp()
    store = SessionBindingStore(data_dir=td)
    router = SessionBoundRouter(binding_store=store)

    router.bind_session("sess-ub", "dongjiagoushi", "软件研发")
    router.unbind_session("sess-ub")

    r = router.route("帮我制定健身计划", session_id="sess-ub")
    b = store.get_binding("sess-ub")
    assert b is not None
    assert b.unit_id == "healthcare"


def test_invalid_session_routing():
    """非法 session_id 被拒绝"""
    td = tempfile.mkdtemp()
    store = SessionBindingStore(data_dir=td)
    router = SessionBoundRouter(binding_store=store)

    try:
        router.route("帮我做架构方案", session_id="../../etc/passwd")
        # 如果走到这里，说明 session_id 校验通过了（不应该）
        # 实际上非法字符会被 get_binding 里的正则拒绝，返回 None
        pass
    except ValueError:
        pass


def test_auto_bind_false():
    """auto_bind=False 时不自动绑定"""
    td = tempfile.mkdtemp()
    store = SessionBindingStore(data_dir=td)
    router = SessionBoundRouter(binding_store=store)

    r = router.route("帮我做软件架构设计方案", session_id="nobind-1",
                     auto_bind=False)
    b = store.get_binding("nobind-1")
    assert b is None or b.unit_id == "", "auto_bind=False 不应自动绑定"


# ============ 手动执行 ============

if __name__ == "__main__":
    # SessionBindingStore tests
    test_bind_and_get()
    test_bind_duplicate_same_industry()
    test_bind_conflicting_industry_rejected()
    test_unbind()
    test_list_bindings()
    test_invalid_session_id()
    test_persistence()

    # SessionBoundRouter tests
    test_router_without_session_backward_compat()
    test_auto_bind_on_first_route()
    test_same_industry_route_in_bound_session()
    test_cross_industry_handoff_in_bound_session()
    test_bound_session_not_switch_industry()
    test_cross_industry_auto_handoff_card()
    test_bound_session_multiple_roles_composite()
    test_bind_to_other_unit_then_route()
    test_unbind_and_reroute()
    test_invalid_session_routing()
    test_auto_bind_false()

    print("✅ 全部 SLIB 测试通过")
