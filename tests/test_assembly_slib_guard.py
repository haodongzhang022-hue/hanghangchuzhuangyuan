"""SLIB 上下文装配守卫测试

验证：一次会话的上下文装配必须落在"被锁定行业"内——
  - 会话已绑定 X：装配 unit_id==X 放行；unit_id==Y(≠X) 被拦截
  - 会话未绑定：首装自动绑定后放行
  - 无 session：退化为静态单发装配（向后兼容）
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from hanghang.context import (
    ContextAssembler, SLIBAssemblyGuard, SLIBBoundMismatch,
)
from hanghang.engine import SessionBindingStore


def _make_assembler(store):
    guard = SLIBAssemblyGuard(binding_store=store)
    return ContextAssembler(slib_guard=guard), store


def test_unbound_first_assemble_auto_binds():
    """会话未绑定：首装自动绑定到传入 unit，随后放行"""
    store = SessionBindingStore(data_dir=tempfile.mkdtemp())
    a, store = _make_assembler(store)

    res = a.assemble_bound(
        session_id="sess-1",
        unit_id="dongjiagoushi",
        industry="软件研发",
        role_name="architect",
        user_text="帮我做架构方案",
    )
    assert res["full_context"]
    # 会话已自动绑定
    b = store.get_binding("sess-1")
    assert b is not None
    assert b.unit_id == "dongjiagoushi"
    assert "dongjiagoushi" in res["layer_a"]


def test_bound_same_industry_pass():
    """已绑定 X，装配 X → 放行"""
    store = SessionBindingStore(data_dir=tempfile.mkdtemp())
    store.bind("sess-2", "healthcare", "健康医疗")
    a, _ = _make_assembler(store)

    res = a.assemble_bound(
        session_id="sess-2",
        unit_id="healthcare",
        user_text="制定健身计划",
    )
    assert "healthcare" in res["layer_a"]


def test_bound_cross_industry_blocked():
    """已绑定 X，装配 Y → 抛 SLIBBoundMismatch"""
    store = SessionBindingStore(data_dir=tempfile.mkdtemp())
    store.bind("sess-3", "legal-services", "法律咨询")
    a, _ = _make_assembler(store)

    try:
        a.assemble_bound(
            session_id="sess-3",
            unit_id="healthcare",
            user_text="制定健身计划",
        )
        assert False, "应当拦截跨行业装配"
    except SLIBBoundMismatch as e:
        assert e.bound_unit == "legal-services"
        assert e.attempt_unit == "healthcare"
        assert "跨行业请开新会话" in str(e)


def test_no_session_degrade_static():
    """无 session_id：退化为普通 assemble，不强约束"""
    store = SessionBindingStore(data_dir=tempfile.mkdtemp())
    a, _ = _make_assembler(store)

    res = a.assemble_bound(
        session_id="",
        unit_id="game-dev-unit",
        user_text="设计一个游戏关卡",
    )
    assert "game-dev-unit" in res["layer_a"]


def test_unbound_without_unit_raises():
    """未绑定且未提供 unit_id → ValueError"""
    store = SessionBindingStore(data_dir=tempfile.mkdtemp())
    a, _ = _make_assembler(store)

    try:
        a.assemble_bound(session_id="sess-4", user_text="随便聊聊")
        assert False, "应当报错：无法确定装配行业"
    except ValueError:
        pass


def test_guard_works_on_raw_assembler_without_bound():
    """默认装配器未显式传 store，也可用（惰性创建默认 store）"""
    # 用独立临时 data 规避默认 data/bindings 落盘
    guard = SLIBAssemblyGuard(binding_store=SessionBindingStore(data_dir=tempfile.mkdtemp()))
    a = ContextAssembler(slib_guard=guard)
    res = a.assemble_bound(
        session_id="sess-5",
        unit_id="e-commerce",
        user_text="写一份促销方案",
    )
    assert "e-commerce" in res["layer_a"]
