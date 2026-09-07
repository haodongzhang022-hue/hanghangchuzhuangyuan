"""M9+ 版本化冲突仲裁与审核测试（ConflictArbiter）

覆盖：
- 字段级 StateDiff 计算（任务新增/删除/字段修改）
- diffs_overlap 冲突重叠检测
- 无重叠 → 自动合并（双方变更均保留）
- 有重叠 → ReviewTicket 待审核
- 审核 keep_a / keep_b / merge / reject
- 票据持久化与查询
- 与 OwnershipGuard 集成（arbitrate_conflict 流程）
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from hanghang.engine import (
    StateManager, OwnershipGuard, StateConflict,
    ConflictArbiter, ReviewTicket,
    diff_state, diffs_overlap,
    StateCard,
)


def _make_base(prefix: str) -> StateManager:
    """创建一个带基础任务的 StateCard"""
    tmpdir = tempfile.mkdtemp(prefix=prefix)
    mgr = StateManager(data_dir=tmpdir)
    mgr.create_card("sess-arb", objective="仲裁测试")
    mgr.add_task("sess-arb", "Task 1", task_type="normal")
    mgr.add_task("sess-arb", "Task 2", task_type="normal")
    # Reset version to a clean state for diff analysis
    card = mgr.get_card("sess-arb")
    card.version = 0
    mgr.save_card(card)
    return mgr


def test_diff_state_task_added():
    """diff_state: 检测新增任务"""
    mgr = _make_base("t-diff-add")
    base = mgr.get_card("sess-arb")
    target = mgr.get_card("sess-arb")
    target.add_task("New Task", task_type="normal")
    d = diff_state(base, target)
    assert len(d.task_added) == 1
    assert len(d.task_removed) == 0
    assert len(d.task_changes) == 0


def test_diff_state_field_change():
    """diff_state: 检测字段级修改"""
    mgr = _make_base("t-diff-field")
    base = mgr.get_card("sess-arb")
    target = mgr.get_card("sess-arb")
    target.update_task("sess-arb-0001", state="done")
    d = diff_state(base, target)
    assert len(d.task_changes) == 1
    assert d.task_changes[0].field == "state"
    assert d.task_changes[0].new_value == "done"
    assert len(d.task_added) == 0


def test_diffs_overlap_detected():
    """diffs_overlap: 同一任务同一字段修改 → 检测到重叠"""
    mgr = _make_base("t-overlap")
    base = mgr.get_card("sess-arb")
    # Agent A: mark task 1 as done
    card_a = mgr.get_card("sess-arb")
    card_a.update_task("sess-arb-0001", state="done")
    # Agent B: mark task 1 as blocked (same field)
    card_b = mgr.get_card("sess-arb")
    card_b.update_task("sess-arb-0001", state="blocked")

    da = diff_state(base, card_a)
    db = diff_state(base, card_b)
    overlaps = diffs_overlap(da, db)
    assert len(overlaps) == 1
    assert overlaps[0]["change_kind"] == "same_field_conflict"
    assert overlaps[0]["task_id"] == "sess-arb-0001"
    assert overlaps[0]["field"] == "state"


def test_diffs_no_overlap_non_conflicting():
    """diffs_overlap: 修改不同字段 → 无重叠"""
    mgr = _make_base("t-no-overlap")
    base = mgr.get_card("sess-arb")
    # Agent A: change task 1 state
    card_a = mgr.get_card("sess-arb")
    card_a.update_task("sess-arb-0001", state="done")
    # Agent B: change task 1 objective (different field)
    card_b = mgr.get_card("sess-arb")
    card_b.update_task("sess-arb-0001", objective="B的目标")

    da = diff_state(base, card_a)
    db = diff_state(base, card_b)
    overlaps = diffs_overlap(da, db)
    assert len(overlaps) == 0


def test_auto_merge_non_overlapping():
    """无重叠 → 自动合并，双方变更均保留"""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = StateManager(data_dir=tmpdir)
        mgr.create_card("sess-auto", objective="自动合并")
        mgr.add_task("sess-auto", "Task 1", task_type="normal")
        mgr.add_task("sess-auto", "Task 2", task_type="normal")
        base = mgr.get_card("sess-auto")
        base.version = 0
        mgr.save_card(base)

        # Agent A: mark task 1 as done
        card_a = mgr.get_card("sess-auto")
        card_a.update_task("sess-auto-0001", state="done")
        # Agent B: add a new task 3
        card_b = mgr.get_card("sess-auto")
        card_b.add_task("Task 3", task_type="normal")

        arbiter = ConflictArbiter(data_dir=os.path.join(tmpdir, "arb"),
                                  state_manager=mgr)
        ticket = arbiter.capture_conflict(
            session_id="sess-auto",
            base_card=base,
            conflicting_card=card_b,
            current_card=card_a,
            arbiter_name="agent_b",
        )
        assert ticket.status == "resolved"
        assert ticket.resolution == "merge"
        # Merged state: task 1 is done AND task 3 was added
        final_card = mgr.get_card("sess-auto")
        task1 = final_card.get_task("sess-auto-0001")
        assert task1.state == "done"
        assert any(t.title == "Task 3" for t in final_card.tasks)


def test_review_ticket_pending_on_overlap():
    """有重叠 → ReviewTicket 保持 pending，等待审核"""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = StateManager(data_dir=tmpdir)
        mgr.create_card("sess-conf", objective="冲突")
        mgr.add_task("sess-conf", "Task 1", task_type="normal")
        mgr.add_task("sess-conf", "Task 2", task_type="normal")
        base = mgr.get_card("sess-conf")
        base.version = 0
        mgr.save_card(base)

        card_a = mgr.get_card("sess-conf")
        card_a.update_task("sess-conf-0001", state="done")
        card_b = mgr.get_card("sess-conf")
        card_b.update_task("sess-conf-0001", state="blocked")

        arbiter = ConflictArbiter(data_dir=os.path.join(tmpdir, "arb"),
                                  state_manager=mgr)
        ticket = arbiter.capture_conflict(
            session_id="sess-conf",
            base_card=base,
            conflicting_card=card_b,
            current_card=card_a,
            arbiter_name="agent_b",
        )
        assert ticket.status == "pending"
        assert ticket.is_auto_mergeable == False
        assert len(ticket.overlaps) >= 1
        # Ticket persists
        loaded = arbiter.get_ticket(ticket.id)
        assert loaded is not None
        assert loaded.session_id == "sess-conf"


def test_review_keep_a():
    """审核: keep_a → 保留已提交方版本"""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = StateManager(data_dir=tmpdir)
        mgr.create_card("sess-rv-a", objective="审核")
        mgr.add_task("sess-rv-a", "Task 1", task_type="normal")
        base = mgr.get_card("sess-rv-a")
        base.version = 0
        mgr.save_card(base)

        card_a = mgr.get_card("sess-rv-a")
        card_a.update_task("sess-rv-a-0001", state="done")
        card_b = mgr.get_card("sess-rv-a")
        card_b.update_task("sess-rv-a-0001", state="blocked")

        arbiter = ConflictArbiter(data_dir=os.path.join(tmpdir, "arb"),
                                  state_manager=mgr)
        ticket = arbiter.capture_conflict(
            session_id="sess-rv-a",
            base_card=base,
            conflicting_card=card_b,
            current_card=card_a,
            arbiter_name="agent_b",
        )
        # Review: keep A
        resolved = arbiter.review(ticket.id, "keep_a",
                                  resolver="reviewer-1", reason="A的修改合理")
        assert resolved.status == "resolved"
        assert resolved.resolution == "keep_a"
        # StateCard should have task 1 as done (A's version)
        final = mgr.get_card("sess-rv-a")
        assert final.get_task("sess-rv-a-0001").state == "done"


def test_review_keep_b():
    """审核: keep_b → 冲突方版本胜出"""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = StateManager(data_dir=tmpdir)
        mgr.create_card("sess-rv-b", objective="审核B")
        mgr.add_task("sess-rv-b", "Task 1", task_type="normal")
        base = mgr.get_card("sess-rv-b")
        base.version = 0
        mgr.save_card(base)

        card_a = mgr.get_card("sess-rv-b")
        card_a.update_task("sess-rv-b-0001", state="done")
        card_b = mgr.get_card("sess-rv-b")
        card_b.update_task("sess-rv-b-0001", state="blocked")

        arbiter = ConflictArbiter(data_dir=os.path.join(tmpdir, "arb"),
                                  state_manager=mgr)
        ticket = arbiter.capture_conflict(
            session_id="sess-rv-b",
            base_card=base,
            conflicting_card=card_b,
            current_card=card_a,
            arbiter_name="agent_b",
        )
        resolved = arbiter.review(ticket.id, "keep_b",
                                  resolver="reviewer-1", reason="B更有理")
        final = mgr.get_card("sess-rv-b")
        assert final.get_task("sess-rv-b-0001").state == "blocked"


def test_list_pending_tickets():
    """list_pending: 列出待审核票据"""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = StateManager(data_dir=tmpdir)
        mgr.create_card("sess-list", objective="list")
        mgr.add_task("sess-list", "Task 1", task_type="normal")
        base = mgr.get_card("sess-list")
        base.version = 0
        mgr.save_card(base)

        card_a = mgr.get_card("sess-list")
        card_a.update_task("sess-list-0001", state="done")
        card_b = mgr.get_card("sess-list")
        card_b.update_task("sess-list-0001", state="blocked")

        arbiter = ConflictArbiter(data_dir=os.path.join(tmpdir, "arb"),
                                  state_manager=mgr)
        arbiter.capture_conflict(
            session_id="sess-list",
            base_card=base,
            conflicting_card=card_b,
            current_card=card_a,
            arbiter_name="agent_b",
        )
        pending = arbiter.list_pending()
        assert len(pending) == 1


def test_ownership_guard_arbitrate_integration():
    """OwnershipGuard.arbitrate_conflict: 版本冲突走仲裁而非直接拒绝"""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = StateManager(data_dir=tmpdir)
        mgr.create_card("sess-guard-arb", objective="guard集成")
        mgr.add_task("sess-guard-arb", "Task 1", task_type="normal")
        base = mgr.get_card("sess-guard-arb")
        base.version = 0
        mgr.save_card(base)

        # Agent A commits first
        guard_a = OwnershipGuard("sess-guard-arb", mgr, secretary="agent_a")
        guard_a.claim()
        guard_a.guarded_update_task_state("sess-guard-arb-0001", "done",
                                          base_version=guard_a.version())
        guard_a.release()

        # Agent B tries to commit conflicting change
        guard_b = OwnershipGuard("sess-guard-arb", mgr, secretary="agent_b")
        # Build proposed card with B's change
        proposed = guard_b.build_proposed(
            lambda c: c.update_task("sess-guard-arb-0001", state="blocked")
        )
        # Capture the base snapshot (agent B's view before agent A modified)
        # In real scenarios this would be captured when B read the card
        base_snapshot = StateCard.from_dict(base.to_dict())
        # Trigger arbitration with exact base snapshot
        result = guard_b.arbitrate_conflict(
            base_version=0,
            proposed_card=proposed,
            capture_base=base_snapshot,
            reason="agent_b 想修改同一任务状态",
        )
        # Should return a ReviewTicket
        assert hasattr(result, 'id')
        assert result.status in ("pending", "resolved")


if __name__ == "__main__":
    test_diff_state_task_added()
    test_diff_state_field_change()
    test_diffs_overlap_detected()
    test_diffs_no_overlap_non_conflicting()
    test_auto_merge_non_overlapping()
    test_review_ticket_pending_on_overlap()
    test_review_keep_a()
    test_review_keep_b()
    test_list_pending_tickets()
    test_ownership_guard_arbitrate_integration()
    print("✅ 版本化冲突仲裁与审核测试全部通过")


def _remove_task(card, task_id):
    """构造性工具：从 StateCard 上移除指定任务（供构造 B 删除任务场景）"""
    card.tasks = [t for t in card.tasks if t.task_id != task_id]
    card.version += 1
    card.updated_at = __import__("time").strftime("%Y-%m-%d %H:%M:%S")
    return card


def test_diffs_overlap_changed_vs_removed_conflict():
    """Bug修复: A 改字段 + B 删同一任务 → 判为冲突(不自动合并)"""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = StateManager(data_dir=tmpdir)
        mgr.create_card("sess-cr", objective="冲突")
        mgr.add_task("sess-cr", "Task 1", task_type="normal")
        base = mgr.get_card("sess-cr")
        base.version = 0
        mgr.save_card(base)

        # Agent A: 修改 task1 的 summary 字段
        card_a = mgr.get_card("sess-cr")
        card_a.update_task("sess-cr-0001", summary="A 补充的说明")
        # Agent B: 删除 task1
        card_b = mgr.get_card("sess-cr")
        _remove_task(card_b, "sess-cr-0001")

        da = diff_state(base, card_a)
        db = diff_state(base, card_b)
        overlaps = diffs_overlap(da, db)
        assert len(overlaps) == 1, f"应检测到冲突，实际 overlaps={overlaps}"
        assert overlaps[0]["change_kind"] == "changed_removed_same_task"
        assert overlaps[0]["task_id"] == "sess-cr-0001"

        # 端到端：capture_conflict 应产生 pending 票据而非静默自动合并
        arbiter = ConflictArbiter(data_dir=os.path.join(tmpdir, "arb"),
                                  state_manager=mgr)
        ticket = arbiter.capture_conflict(
            session_id="sess-cr",
            base_card=base,
            conflicting_card=card_b,
            current_card=card_a,
            arbiter_name="agent_b",
        )
        assert ticket.status == "pending", \
            f"A改字段+B删任务不应自动合并，应 pending，实际={ticket.status}"
        # 决不允许"宣称保留实则丢失"：A 对 task1 的修改必须仍在（未被静默丢弃）
        assert not ticket.is_auto_mergeable


def test_diffs_overlap_removed_vs_changed_conflict():
    """Bug修复(对称): A 删任务 + B 改该任务字段 → 判为冲突(不自动合并)"""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = StateManager(data_dir=tmpdir)
        mgr.create_card("sess-rc", objective="冲突")
        mgr.add_task("sess-rc", "Task 1", task_type="normal")
        base = mgr.get_card("sess-rc")
        base.version = 0
        mgr.save_card(base)

        # Agent A: 删除 task1
        card_a = mgr.get_card("sess-rc")
        _remove_task(card_a, "sess-rc-0001")
        # Agent B: 修改 task1 的 summary 字段
        card_b = mgr.get_card("sess-rc")
        card_b.update_task("sess-rc-0001", summary="B 想改说明")

        da = diff_state(base, card_a)
        db = diff_state(base, card_b)
        overlaps = diffs_overlap(da, db)
        assert len(overlaps) == 1
        assert overlaps[0]["change_kind"] == "changed_removed_same_task"

        arbiter = ConflictArbiter(data_dir=os.path.join(tmpdir, "arb"),
                                  state_manager=mgr)
        ticket = arbiter.capture_conflict(
            session_id="sess-rc",
            base_card=base,
            conflicting_card=card_b,
            current_card=card_a,
            arbiter_name="agent_b",
        )
        assert ticket.status == "pending"


def test_auto_merge_verifies_both_retained():
    """自动合并后复核：非重叠变更(A改字段+B新增任务)双方均保留"""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = StateManager(data_dir=tmpdir)
        mgr.create_card("sess-vfy", objective="合并复核")
        mgr.add_task("sess-vfy", "Task 1", task_type="normal")
        base = mgr.get_card("sess-vfy")
        base.version = 0
        mgr.save_card(base)

        # Agent A: 修改 task1 的 summary
        card_a = mgr.get_card("sess-vfy")
        card_a.update_task("sess-vfy-0001", summary="A 的说明")
        # Agent B: 新增 task3（不重叠）
        card_b = mgr.get_card("sess-vfy")
        card_b.add_task("Task 3", task_type="normal")

        arbiter = ConflictArbiter(data_dir=os.path.join(tmpdir, "arb"),
                                  state_manager=mgr)
        ticket = arbiter.capture_conflict(
            session_id="sess-vfy",
            base_card=base,
            conflicting_card=card_b,
            current_card=card_a,
            arbiter_name="agent_b",
        )
        assert ticket.status == "resolved", f"应自动合并，实际={ticket.status}"
        final = mgr.get_card("sess-vfy")
        # A 的字段修改保留
        assert final.get_task("sess-vfy-0001").summary == "A 的说明"
        # B 的新增任务保留
        assert any(t.title == "Task 3" for t in final.tasks)
        assert "双方变更均已保留" in ticket.resolution_note


def test_review_stale_guard_raises():
    """版本回退防护: 冲突后会话已有更新时，review 不应静默覆写旧快照"""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = StateManager(data_dir=tmpdir)
        mgr.create_card("sess-stale", objective="stale")
        mgr.add_task("sess-stale", "Task 1", task_type="normal")
        base = mgr.get_card("sess-stale")
        base.version = 0
        mgr.save_card(base)

        # Agent A 提交(落盘到 v1)，作为已提交方当前状态
        committed = mgr.get_card("sess-stale")
        committed.update_task("sess-stale-0001", state="done")
        mgr.save_card(committed)
        # Agent B 基于冲突前 base(v0) 构造 proposed
        card_b = mgr.get_card("sess-stale")
        card_b = StateCard.from_dict(base.to_dict())
        card_b.update_task("sess-stale-0001", state="blocked")

        arbiter = ConflictArbiter(data_dir=os.path.join(tmpdir, "arb"),
                                  state_manager=mgr)
        ticket = arbiter.capture_conflict(
            session_id="sess-stale",
            base_card=base,
            conflicting_card=card_b,
            current_card=mgr.get_card("sess-stale"),
            arbiter_name="agent_b",
        )
        # 冲突后再来一笔新提交并落盘（推进到更高版本），模拟审核滞后
        newer = mgr.get_card("sess-stale")
        newer.update_task("sess-stale-0001", summary="滞后期间的中间变更")
        mgr.save_card(newer)
        raised = False
        try:
            arbiter.review(ticket.id, "keep_a", resolver="r", reason="x")
        except ValueError:
            raised = True
        assert raised, "会话已有更新时 review 应拒绝静默覆写旧快照"


if __name__ == "__main__":
    test_diff_state_task_added()
    test_diff_state_field_change()
    test_diffs_overlap_detected()
    test_diffs_no_overlap_non_conflicting()
    test_auto_merge_non_overlapping()
    test_review_ticket_pending_on_overlap()
    test_review_keep_a()
    test_review_keep_b()
    test_list_pending_tickets()
    test_ownership_guard_arbitrate_integration()
    test_diffs_overlap_changed_vs_removed_conflict()
    test_diffs_overlap_removed_vs_changed_conflict()
    test_auto_merge_verifies_both_retained()
    test_review_stale_guard_raises()
    print("✅ 版本化冲突仲裁与审核测试全部通过")
