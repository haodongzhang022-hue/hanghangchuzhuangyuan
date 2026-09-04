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


if __name__ == "__main__":
    test_create_and_get_handoff()
    test_update_status()
    test_list_pending()
    print("✅ 交接总线测试通过")
