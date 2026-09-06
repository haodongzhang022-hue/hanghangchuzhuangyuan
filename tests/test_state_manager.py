"""M9 状态管理层测试"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from hanghang.engine import (
    StateManager, FoldEngine, HierarchySubmitter,
    StateCard, TaskRecord, TaskState, TaskType, FoldState,
)


def test_create_and_get_state_card():
    """创建并读取 StateCard"""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = StateManager(data_dir=tmpdir)
        card = mgr.create_card(
            session_id="sess-1",
            objective="实现M9状态管理",
            unit_id="dongjiagoushi",
            role_name="secretary",
        )
        assert card is not None
        assert card.session_id == "sess-1"
        assert card.objective == "实现M9状态管理"
        assert card.id is not None

        # 重新读取
        fetched = mgr.get_card("sess-1")
        assert fetched is not None
        assert fetched.session_id == "sess-1"
        assert fetched.objective == "实现M9状态管理"


def test_add_and_update_task():
    """添加和更新任务"""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = StateManager(data_dir=tmpdir)
        card = mgr.create_card("sess-2", objective="测试任务管理")

        # 添加普通任务
        task = mgr.add_task(
            session_id="sess-2",
            title="实现状态模型",
            files=["models.py"],
            tools=["python3"],
        )
        assert task is not None
        assert task.task_id == "sess-2-0001"
        assert task.fold == FoldState.COLLAPSED.value  # 普通任务默认折叠

        # 添加交付任务
        task2 = mgr.add_task(
            session_id="sess-2",
            title="交付完整模块",
            task_type=TaskType.DELIVERABLE.value,
            files=["__init__.py"],
        )
        assert task2 is not None
        assert task2.fold == FoldState.EXPANDED.value  # 交付任务默认展开

        # 更新状态
        ok = mgr.update_task_state("sess-2", task.task_id, TaskState.DONE.value)
        assert ok is True

        # 非法状态迁移（done → in_progress 不允许）
        ok2 = mgr.update_task_state("sess-2", task.task_id, TaskState.IN_PROGRESS.value)
        assert ok2 is False

        # 验证更新结果
        card2 = mgr.get_card("sess-2")
        assert card2 is not None
        assert card2.get_task(task.task_id).state == TaskState.DONE.value


def test_fold_engine_default_folding():
    """折叠引擎：默认恒折叠非交付任务"""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = StateManager(data_dir=tmpdir)
        mgr.create_card("sess-3", objective="折叠测试")

        # 添加三个任务：两个普通 + 一个交付
        t1 = mgr.add_task("sess-3", "任务A", task_type=TaskType.NORMAL.value)
        t2 = mgr.add_task("sess-3", "任务B", task_type=TaskType.NORMAL.value)
        t3 = mgr.add_task("sess-3", "交付C", task_type=TaskType.DELIVERABLE.value)

        # 手动更新 t1 为 in_progress
        mgr.update_task_state("sess-3", t2.task_id, TaskState.IN_PROGRESS.value)

        # 执行折叠策略
        engine = FoldEngine("sess-3")
        card = mgr.get_card("sess-3")
        card = engine.auto_fold_policy(card)
        mgr._save(card)

        # 验证：交付任务 + 当前执行任务展开，其他折叠
        expanded = mgr.get_expanded_tasks("sess-3")
        collapsed = mgr.get_collapsed_tasks("sess-3")

        expanded_ids = {t.task_id for t in expanded}
        collapsed_ids = {t.task_id for t in collapsed}

        assert t3.task_id in expanded_ids  # 交付任务展开
        assert t2.task_id in expanded_ids  # 当前执行任务展开
        assert t1.task_id in collapsed_ids  # 普通任务折叠

        assert len(expanded) == 2
        assert len(collapsed) == 1


def test_compact_context_no_full_content():
    """压缩上下文不含原文全量"""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = StateManager(data_dir=tmpdir)
        mgr.create_card("sess-4", objective="上下文压缩")

        t1 = mgr.add_task("sess-4", "调研任务", files=["research.md"],
                          content_ref="sess-4-seg001")
        t2 = mgr.add_task("sess-4", "执行任务", files=["impl.py"])
        mgr.update_task_state("sess-4", t2.task_id, TaskState.IN_PROGRESS.value)
        t3 = mgr.add_task("sess-4", "交付任务", task_type=TaskType.DELIVERABLE.value)

        # 执行折叠策略
        engine = FoldEngine("sess-4")
        card = mgr.get_card("sess-4")
        card = engine.auto_fold_policy(card)
        mgr._save(card)

        ctx = engine.compact_context(card)
        # 展开的任务应携带要素信息
        assert "sess-4-0002" in ctx  # 当前执行任务
        assert "sess-4-0003" in ctx  # 交付任务

        # 折叠任务只显示编号和引用，不含正文
        assert "sess-4-0001" in ctx
        assert "调研任务" not in ctx  # 折叠任务不携带标题正文（只带编号ref）

        # 引用编号应存在（可检索）
        assert "sess-4-seg001" in ctx or "ref" in ctx


def test_hierarchy_submit():
    """层级向上提交：只传汇总不传全量"""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = StateManager(data_dir=tmpdir)
        mgr.create_card("sess-5", objective="向下级提交测试")
        mgr.add_task("sess-5", "任务1")
        mgr.add_task("sess-5", "任务2")

        mgr.update_task_state("sess-5", "sess-5-0001", TaskState.DONE.value)

        submitter = HierarchySubmitter(data_dir=tmpdir)
        card = mgr.get_card("sess-5")  # 重新获取最新状态
        sub = submitter.submit_up(
            card, upstream_session="parent-session"
        )
        assert sub["from_session"] == "sess-5"
        assert sub["to_session"] == "parent-session"
        payload = sub["payload"]
        assert payload["task_count"] == 2
        assert payload["done_count"] == 1

        # 检查提交记录
        records = submitter.list_submissions()
        assert len(records) == 1


def test_fold_content_with_content_meta():
    """折叠原文并带元数据"""
    content = """第一段任务内容

第二段任务内容

最终交付内容"""

    engine = FoldEngine("sess-6", unit_id="dongjiagoushi")
    card = engine.fold_content(
        content,
        content_meta={
            "objective": "将内容折叠为任务",
            "files": ["docs/file.md"],
            "tools": ["python3"],
        },
    )
    assert len(card.tasks) == 3
    # 最后一段是交付任务且展开
    last = card.tasks[-1]
    assert last.task_type == TaskType.DELIVERABLE.value
    assert last.fold == FoldState.EXPANDED.value
    # 前面是普通任务且折叠
    assert card.tasks[0].fold == FoldState.COLLAPSED.value
    # 每个任务都有内容引用编号
    assert card.tasks[0].content_ref is not None


if __name__ == "__main__":
    test_create_and_get_state_card()
    test_add_and_update_task()
    test_fold_engine_default_folding()
    test_compact_context_no_full_content()
    test_hierarchy_submit()
    test_fold_content_with_content_meta()
    print("✅ M9 状态管理层测试全部通过")
