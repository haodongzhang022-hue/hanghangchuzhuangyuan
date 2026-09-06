"""M9 状态管理层 · CLI 子命令"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from hanghang.engine import StateManager, FoldEngine, HierarchySubmitter


def cmd_state_init(args):
    """初始化一张 StateCard"""
    mgr = StateManager()
    card = mgr.create_card(
        session_id=args.session,
        objective=args.objective or "",
        unit_id=args.unit or "",
        role_name=args.role or "secretary",
    )
    print(f"StateCard 已创建:")
    print(f"  会话: {card.session_id}")
    print(f"  目标: {card.objective or '(无)'}")
    print(f"  维护者: {card.role_name}")
    print(f"  ID: {card.id}")


def cmd_state_add(args):
    """添加任务到 StateCard"""
    mgr = StateManager()
    files = args.files.split(",") if args.files else []
    tools = args.tools.split(",") if args.tools else []
    task = mgr.add_task(
        session_id=args.session,
        title=args.title,
        objective=args.objective or "",
        files=files,
        tools=tools,
        task_type=args.type,
    )
    if task is None:
        print(f"会话 {args.session} 不存在，请先执行 state init")
        return
    print(f"任务已添加: #{task.task_id} {task.title}")


def cmd_state_show(args):
    """查看 StateCard 导航/渲染层"""
    mgr = StateManager()
    card = mgr.get_card(args.session)
    if card is None:
        print(f"会话 {args.session} 不存在 StateCard")
        return
    engine = FoldEngine(card.session_id)
    print(engine.render_navigation(card))


def cmd_state_compact(args):
    """生成压缩上下文（执行 agent 视角）"""
    mgr = StateManager()
    card = mgr.get_card(args.session)
    if card is None:
        print(f"会话 {args.session} 不存在 StateCard")
        return
    engine = FoldEngine(card.session_id)
    ctx = engine.compact_context(card)
    print(ctx if ctx else "(空上下文)")


def cmd_state_update(args):
    """更新任务状态"""
    mgr = StateManager()
    ok = mgr.update_task_state(args.session, args.task, args.state)
    if not ok:
        print(f"更新失败：任务不存在或状态迁移不合法")
        return
    print(f"任务 #{args.task} 状态已更新为 {args.state}")


def cmd_state_fold(args):
    """执行折叠策略"""
    mgr = StateManager()
    card = mgr.apply_fold_policy(args.session)
    if card is None:
        print(f"会话 {args.session} 不存在 StateCard")
        return
    print(f"已应用折叠策略，当前展开任务:")
    for t in mgr.get_expanded_tasks(args.session):
        print(f"  #{t.task_id} {t.title} [{t.state}]")
    collapsed = mgr.get_collapsed_tasks(args.session)
    print(f"已折叠 {len(collapsed)} 个任务（含内容引用可检索）")


def cmd_state_submit(args):
    """向上级提交汇总状态"""
    mgr = StateManager()
    card = mgr.get_card(args.session)
    if card is None:
        print(f"会话 {args.session} 不存在 StateCard")
        return
    submitter = HierarchySubmitter()
    upstream = args.upstream or card.upstream or "root"
    sub = submitter.submit_up(card, upstream_session=upstream)
    payload = sub["payload"]
    print(f"已提交 {sub['from_session']} → {sub['to_session']}")
    print(f"  任务数: {payload['task_count']}")
    print(f"  完成: {payload['done_count']}, 进行中: {payload['in_progress_count']}, "
          f"阻塞: {payload['blocked_count']}")
    print(f"  content_refs: {payload['content_refs']}")


def cmd_state_list(args):
    """列出所有 StateCard"""
    mgr = StateManager()
    cards = mgr.list_cards()
    if not cards:
        print("无 StateCard")
        return
    print(f"共 {len(cards)} 张 StateCard:")
    for c in cards:
        done = sum(1 for t in c.tasks if t.state == "done")
        print(f"  {c.session_id} | {c.objective or '(无目标)'} | "
              f"tasks={len(c.tasks)}, done={done}, role={c.role_name}")
