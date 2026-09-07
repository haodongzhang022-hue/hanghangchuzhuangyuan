"""M5 交接总线测试"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from hanghang.engine import HandoffBus


def test_create_and_get_handoff():
    with tempfile.TemporaryDirectory() as tmpdir:
        bus = HandoffBus(data_dir=tmpdir)
        card = bus.create_handoff(
            source_unit="dongjiagoushi",
            target_unit="game-dev-unit",
            intent="需要为游戏设计一个架构方案",
            context="用户想做一个吃鸡游戏的系统架构设计",
        )
        assert card is not None
        assert card.source_unit == "dongjiagoushi"
        assert card.target_unit == "game-dev-unit"
        assert card.status == "created"
        assert card.id is not None

        # 重新读取
        fetched = bus.get(card.id)
        assert fetched is not None
        assert fetched.intent == "需要为游戏设计一个架构方案"


def test_update_status():
    with tempfile.TemporaryDirectory() as tmpdir:
        bus = HandoffBus(data_dir=tmpdir)
        card = bus.create_handoff(
            source_unit="unitA", target_unit="unitB", intent="test")
        assert card.id is not None

        ok = bus.update_status(card_id=card.id, status="done")
        assert ok is True

        updated = bus.get(card.id)
        assert updated is not None
        assert updated.status == "done"


def test_list_pending():
    with tempfile.TemporaryDirectory() as tmpdir:
        bus = HandoffBus(data_dir=tmpdir)
        bus.create_handoff(source_unit="a", target_unit="b", intent="t1")
        bus.create_handoff(source_unit="c", target_unit="d", intent="t2")
        pending = bus.list_pending()
        assert len(pending) == 2

        # 更新一个为 done 后，pending 应只剩 1
        bus.update_status(pending[0].id, "done")
        pending2 = bus.list_pending()
        assert len(pending2) == 1


def test_handoff_id_no_second_collision():
    """P1 回归：同秒同 source/target 多次创建，交接卡 ID 必须唯一（不互相覆盖）。"""
    import threading

    with tempfile.TemporaryDirectory() as tmpdir:
        bus = HandoffBus(data_dir=tmpdir)

        # 同一 source/target 并发创建多张卡（模拟并发 POST /api/route）
        results = []
        barrier = threading.Barrier(5)

        def create_one():
            barrier.wait()
            card = bus.create_handoff(
                source_unit="same-unit",
                target_unit="same-unit",
                intent=f"并发创建-{threading.get_ident()}",
                context="同秒同源并发创建，ID 不应碰撞",
            )
            results.append(card)

        threads = [threading.Thread(target=create_one) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 所有卡应成功创建且 ID 各不相同
        assert len(results) == 5, f"应创建 5 张卡，实际 {len(results)}"
        ids = {c.id for c in results}
        assert len(ids) == 5, f"ID 存在碰撞: {ids}"

        # 所有 5 张卡都应在磁盘上（未被覆盖）
        for card in results:
            fetched = bus.get(card.id)
            assert fetched is not None, f"交接卡 {card.id} 不存在（可能被覆盖）"
            assert fetched.intent == card.intent


def test_handoff_id_uniqueness_same_second():
    """P1 回归：循环快速创建同 source/target，所有 ID 唯一。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        bus = HandoffBus(data_dir=tmpdir)
        ids = []
        for i in range(20):
            card = bus.create_handoff(
                source_unit="unit-x",
                target_unit="unit-x",
                intent=f"快速创建-{i}",
            )
            ids.append(card.id)

        assert len(set(ids)) == 20, f"ID 存在重复: {len(set(ids))} != 20"


if __name__ == "__main__":
    _tests = [
        test_create_and_get_handoff,
        test_update_status,
        test_list_pending,
        test_handoff_id_no_second_collision,
        test_handoff_id_uniqueness_same_second,
    ]
    passed = 0
    failed = []
    for t in _tests:
        try:
            t()
            print(f"  ✅ {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  ❌ {t.__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed.append(t.__name__)

    print(f"\n通过 {passed}/{len(_tests)} 个测试")
    if failed:
        print(f"失败: {failed}")
        sys.exit(1)
    print("✅ 交接总线测试全部通过")
