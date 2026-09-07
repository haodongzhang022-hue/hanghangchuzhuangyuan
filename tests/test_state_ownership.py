"""M9 秘书并发归属与冲突仲裁测试（OwnershipGuard）

覆盖：
- 归属声明/释放(claim/release)，owner 与 version 演进
- 他人占用时抢占被拒(StateConflict)，force 可强抢
- 越权写被拒(OwnershipDenied)
- 乐观并发冲突：基于旧 base_version 写入被拒(StateConflict)，不静默覆盖
- 未带版本号写向后兼容
- 卡归属为空的"首个写者隐式取得维护权"
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from hanghang.engine import (
    StateManager, OwnershipGuard, StateConflict, OwnershipDenied,
    TaskState,
)


def test_claim_and_release_owner():
    """归属声明/释放：owner 字段随 claim/release 演进，version 单调递增"""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = StateManager(data_dir=tmpdir)
        mgr.create_card("sess-own-1", objective="并发测试")
        g = OwnershipGuard("sess-own-1", mgr, secretary="secre_a")

        assert g.current_owner() == ""      # 初始未归属
        v0 = g.version()
        g.claim()
        assert g.current_owner() == "secre_a"
        assert g.version() > v0             # 归属使版本递增

        g.release()
        assert g.current_owner() == ""      # 释放后无归属


def test_conflict_on_occupied_by_others():
    """他人占用未过期：非 owner 秘书 claim 被拒(StateConflict)，force 可强抢"""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = StateManager(data_dir=tmpdir)
        mgr.create_card("sess-own-2", objective="并发")
        ga = OwnershipGuard("sess-own-2", mgr, secretary="secre_a")
        ga.claim()
        # B 想抢占 A 占用中的卡
        gb = OwnershipGuard("sess-own-2", mgr, secretary="secre_b")
        try:
            gb.claim()
            assert False, "应抛 StateConflict"
        except StateConflict as e:
            assert e.current_owner == "secre_a"
            assert e.requester == "secre_b"
        # 仍归 A
        assert ga.current_owner() == "secre_a"
        # force 可强抢
        gb.claim(force=True)
        assert gb.current_owner() == "secre_b"


def test_lease_expired_allow_reclaim():
    """租约过期后，其他秘书可重新 claim（确定性处置）"""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = StateManager(data_dir=tmpdir)
        mgr.create_card("sess-own-3", objective="过期")
        ga = OwnershipGuard("sess-own-3", mgr, secretary="secre_a")
        ga.claim()
        # 手动把 A 的租约改为已过期
        import time as _t
        lease_path = os.path.join(tmpdir, "sess-own-3.owner.json")
        import json
        with open(lease_path, encoding="utf-8") as f:
            lease = json.load(f)
        lease["until"] = _t.time() - 10   # 已过期
        with open(lease_path, "w", encoding="utf-8") as f:
            json.dump(lease, f)
        # B 可接管（租约过期）
        gb = OwnershipGuard("sess-own-3", mgr, secretary="secre_b")
        gb.claim()   # 不抛异常
        assert gb.current_owner() == "secre_b"


def test_optimistic_version_conflict():
    """乐观并发：基于旧 base_version 写入被拒(StateConflict)，不静默覆盖"""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = StateManager(data_dir=tmpdir)
        mgr.create_card("sess-own-4", objective="乐观锁")
        ga = OwnershipGuard("sess-own-4", mgr, secretary="secre_a")
        ga.claim()
        v0 = ga.version()
        # A 先加一个任务 → 版本变为 v0+1
        ga.guarded_add_task("任务A", base_version=v0)
        v1 = ga.version()
        assert v1 == v0 + 1

        # B(同一 owner 视为获授权) 基于旧版本 v0 再写 → 冲突
        # 注：secretary 用 A 表示同一维护者不同执行，验证版本仲裁本身
        g2 = OwnershipGuard("sess-own-4", mgr, secretary="secre_a")
        try:
            g2.guarded_add_task("任务B-旧版本", base_version=v0)
            assert False, "应抛 StateConflict(基于旧版本)"
        except StateConflict as e:
            assert e.expected_version == v0
            assert e.actual_version == v1
        # 用最新版本写成功
        g2.guarded_add_task("任务B-最新", base_version=v1)
        assert len(mgr.get_card("sess-own-4").tasks) == 2


def test_ownership_denied_for_unprivileged_writer():
    """越权写：卡被 A 占用，B(非 owner、无授权)写被拒(OwnershipDenied)"""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = StateManager(data_dir=tmpdir)
        mgr.create_card("sess-own-5", objective="越权")
        ga = OwnershipGuard("sess-own-5", mgr, secretary="secre_a")
        ga.claim()
        gb = OwnershipGuard("sess-own-5", mgr, secretary="secre_b")
        try:
            gb.guarded_add_task("B想加任务")
            assert False, "应抛 OwnershipDenied"
        except OwnershipDenied:
            pass
        # A 正常写
        ga.guarded_add_task("A加任务", base_version=ga.version())
        assert len(mgr.get_card("sess-own-5").tasks) == 1


def test_first_writer_implicit_owner():
    """卡归属为空时，首个写者隐式取得维护权"""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = StateManager(data_dir=tmpdir)
        mgr.create_card("sess-own-6", objective="隐式归属")
        g = OwnershipGuard("sess-own-6", mgr, secretary="secre_x")
        # 未 claim 直接写
        g.guarded_add_task("首个任务")
        assert g.current_owner() == "secre_x"  # 隐式归属
        card = mgr.get_card("sess-own-6")
        assert len(card.tasks) == 1


def test_base_version_none_backward_compat():
    """不携带 base_version → 放弃乐观检测，向后兼容原用法"""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = StateManager(data_dir=tmpdir)
        mgr.create_card("sess-own-7", objective="兼容")
        g = OwnershipGuard("sess-own-7", mgr, secretary="secre_a")
        g.claim()
        # 不传 base_version 也正常写
        t = g.guarded_add_task("任务", base_version=None)
        assert t is not None
        assert len(mgr.get_card("sess-own-7").tasks) == 1


if __name__ == "__main__":
    test_claim_and_release_owner()
    test_conflict_on_occupied_by_others()
    test_lease_expired_allow_reclaim()
    test_optimistic_version_conflict()
    test_ownership_denied_for_unprivileged_writer()
    test_first_writer_implicit_owner()
    test_base_version_none_backward_compat()
    print("✅ M9 秘书并发归属与冲突仲裁测试全部通过")
