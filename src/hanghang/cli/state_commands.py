"""M9 状态管理层 · CLI 子命令"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from hanghang.engine import StateManager, FoldEngine, HierarchySubmitter
from hanghang.state import SecretaryTree, SecretaryTreeNode


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



def cmd_state_claim(args):
    """秘书声明对 StateCard 的归属/占用（写租约）"""
    from hanghang.engine import OwnershipGuard, StateConflict
    mgr = StateManager()
    if mgr.get_card(args.session) is None:
        print(f"会话 {args.session} 不存在 StateCard，请先执行 state init")
        return
    g = OwnershipGuard(args.session, mgr, secretary=args.role or "secretary")
    try:
        owner = g.claim(force=args.force)
        print(f"归属成功: 秘书 {owner} 已占用会话 {args.session}")
        print(f"  版本号: {g.version()}")
    except StateConflict as e:
        print(f"占用冲突: {e}")
        print(f"  当前 owner: {e.current_owner or '(无)'}")
        print("  如需强制抢占请加 --force")


def cmd_state_release(args):
    """释放本秘书对 StateCard 的归属"""
    from hanghang.engine import OwnershipGuard
    mgr = StateManager()
    if mgr.get_card(args.session) is None:
        print(f"会话 {args.session} 不存在 StateCard")
        return
    g = OwnershipGuard(args.session, mgr, secretary=args.role or "secretary")
    g.release()
    print(f"已释放: 秘书 {args.role or 'secretary'} 释放会话 {args.session} 的归属")


def cmd_state_status(args):
    """查看 StateCard 归属与版本状态（并发观测）"""
    from hanghang.engine import OwnershipGuard
    mgr = StateManager()
    if mgr.get_card(args.session) is None:
        print(f"会话 {args.session} 不存在 StateCard")
        return
    g = OwnershipGuard(args.session, mgr, secretary=args.role or "secretary")
    print(f"会话: {args.session}")
    print(f"  owner: {g.current_owner() or '(未归属)'}")
    print(f"  version: {g.version()}")
    print(f"  当前秘书({g.secretary})是否 owner: {g.is_owner()}")





def cmd_arb_list(args):
    """列出待审核的冲突票据"""
    from hanghang.engine import ConflictArbiter
    arbiter = ConflictArbiter()
    session_filter = getattr(args, 'session', None)
    status_filter = getattr(args, 'status', None)
    if status_filter:
        tickets = arbiter.list_tickets(session_id=session_filter,
                                        status=status_filter)
    else:
        tickets = arbiter.list_pending(session_id=session_filter)
    if not tickets:
        print("无待处理的冲突票据")
        return
    print(f"共 {len(tickets)} 张冲突票据:")
    for t in tickets:
        overlaps_count = len(t.overlaps) if t.overlaps else 0
        print(f"  {t.id} | {t.session_id} | 状态={t.status} | "
              f"重叠={overlaps_count}处 | {t.created_at}")


def cmd_arb_show(args):
    """查看冲突票据详情"""
    from hanghang.engine import ConflictArbiter
    arbiter = ConflictArbiter()
    ticket = arbiter.get_ticket(args.ticket)
    if ticket is None:
        print(f"票据不存在: {args.ticket}")
        return
    print(ticket.summarize())


def cmd_arb_review(args):
    """执行审核决策: keep_a / keep_b / merge / reject"""
    from hanghang.engine import ConflictArbiter
    arbiter = ConflictArbiter()
    try:
        ticket = arbiter.review(
            ticket_id=args.ticket,
            decision=args.decision,
            resolver=args.resolver or "cli-user",
            reason=args.reason or "",
        )
        print(f"✅ 审核完成: {ticket.id}")
        print(f"  状态: {ticket.status}")
        print(f"  决策: {ticket.resolution}")
        if ticket.reason:
            print(f"  理由: {ticket.reason}")
        if ticket.resolution_note:
            print(f"  说明: {ticket.resolution_note}")
    except Exception as e:
        print(f"审核失败: {e}")


def cmd_arb_diff(args):
    """查看冲突票据的 A/B 双方字段级差异（版本 vs 版本）"""
    from hanghang.engine import ConflictArbiter, diff_state
    arbiter = ConflictArbiter()

    ticket = arbiter.get_ticket(args.ticket)
    if ticket is None:
        print(f"票据不存在: {args.ticket}")
        return

    base_card = ticket.base_card or ticket.card_a
    diff_a = diff_state(base_card, ticket.card_a)
    diff_b = diff_state(base_card, ticket.card_b)

    print(f"票据 {ticket.id} 字段级差异 (会话 {ticket.session_id}, "
          f"A_v={ticket.version_a}, B_v={ticket.version_b})")

    def _render(tag, d):
        lines = []
        if d.task_added:
            lines.append(f"  {tag} 新增任务: " +
                         ", ".join(t.get("task_id", "") for t in d.task_added))
        if d.task_removed:
            lines.append(f"  {tag} 删除任务: {', '.join(d.task_removed)}")
        for ch in d.task_changes:
            lines.append(f"  {tag} {ch.task_id}.{ch.field}: "
                         f"{ch.old_value!r} → {ch.new_value!r}")
        return lines

    print("— 已提交方 A (相对 base):")
    a_lines = _render("[A]", diff_a)
    print("\n".join(a_lines) if a_lines else "  (无变更)")
    print("— 冲突方 B (相对 base):")
    b_lines = _render("[B]", diff_b)
    print("\n".join(b_lines) if b_lines else "  (无变更)")
    if ticket.overlaps:
        print(f"⚠️ 重叠冲突 {len(ticket.overlaps)} 处，建议 arb show 查看详情后 "
              f"用 arb review 裁决。")



def cmd_state_search(args):
    """在 StateCards 中搜索任务（M8 跨会话检索集成）"""
    from hanghang.engine import FoldEngine, StateManager
    mgr = StateManager()
    engine = FoldEngine("")
    cards = mgr.list_cards()
    if not cards:
        print("无 StateCard 可搜索")
        return
    results = engine.search_tasks(cards, args.keyword)
    if not results:
        print(f"未找到包含 '{args.keyword}' 的任务")
        return
    print(f"在 {len(cards)} 张 StateCard 中搜索 '{args.keyword}'，"
          f"命中 {len(results)} 个任务:")
    for r in results:
        fold_mark = "📁" if r["fold"] == "collapsed" else "📂"
        print(f"  {fold_mark} [{r['session_id']}] {r['task_id']} "
              f"{r['title']} ({r['state']})")
        if r["field_hit"]:
            print(f"      命中字段: {', '.join(r['field_hit'])}")


# ==== 秘书长多级树 CLI ====

def cmd_tree_init(args):
    """初始化一棵秘书树（创建树对象）"""
    tree = SecretaryTree(tree_name=args.name)
    # 注册根节点
    tree.register_node(
        session_id=args.root or args.name,
        role_name=args.role or "secretary",
        display_name=args.display or "秘书长",
        objective=args.objective or "",
    )
    print(f"秘书树已创建: {args.name}")
    print(f"  根节点: {args.root or args.name} ({args.display or '秘书长'})")
    print(f"  目标: {args.objective or '(无)'}")


def cmd_tree_register(args):
    """向树注册一个秘书节点"""
    tree = SecretaryTree(tree_name=args.name)
    node = tree.register_node(
        session_id=args.session,
        role_name=args.role or "secretary",
        display_name=args.display or "",
        objective=args.objective or "",
        parent_session=args.parent,
    )
    print(f"节点已注册: {node.session_id}")
    print(f"  角色: {node.role_name}, 显示名: {node.display_name}")
    if args.parent:
        print(f"  父节点: {args.parent}")


def cmd_tree_link(args):
    """建立父子关系"""
    tree = SecretaryTree(tree_name=args.name)
    ok = tree.link(args.parent, args.child)
    if ok:
        print(f"已建立关系: {args.parent} → {args.child}")
    else:
        print(f"建立关系失败: 节点不存在")


def cmd_tree_show(args):
    """渲染整棵树的导航视图"""
    tree = SecretaryTree(tree_name=args.name)
    mgr = StateManager()
    rendered = tree.render_tree(state_manager=mgr)
    print(rendered)


def cmd_tree_rollup(args):
    """执行整棵树的逐级汇总"""
    tree = SecretaryTree(tree_name=args.name)
    mgr = StateManager()
    rollup = tree.rollup(state_manager=mgr)
    print(f"🌳 秘书树 Rollup: {args.name}")
    print(f"    根节点: {rollup['root_session']}")
    for lvl in rollup.get('levels', []):
        depth = lvl['depth']
        for node in lvl['nodes']:
            label = "🏛" if depth == 0 else "📋"
            print(f"  depth={depth} {label} {node['session_id']} "
                  f"({node['role_name']}) tasks={node.get('task_count', 0)} "
                  f"done={node.get('done_count', 0)}")


def cmd_tree_submit_chain(args):
    """沿路径逐级向上提交"""
    mgr = StateManager()
    tree = SecretaryTree(tree_name=args.name)
    submitter = HierarchySubmitter()
    card = mgr.get_card(args.session)
    if card is None:
        print(f"会话 {args.session} 不存在 StateCard")
        return
    subs = submitter.submit_chain_up(card, tree, state_manager=mgr)
    if not subs:
        print("无可提交层级")
        return
    for s in subs:
        if s.get("level_skipped"):
            # 断链记录：该层缺卡/无 state_manager，已跳过并显式提示
            print(f"⚠️ 跳过断链层: {s.get('session')} -> "
                  f"{s.get('parent_session')} ({s.get('reason')})")
        else:
            print(f"已提交: {s['from_session']} -> {s['to_session']}")


def cmd_tree_list(args):
    """列出所有树节点"""
    tree = SecretaryTree(tree_name=args.name)
    if not tree.nodes:
        print(f"树 {args.name} 为空")
        return
    print(f"🌳 树 {args.name} 共 {len(tree.nodes)} 个节点:")
    for sid, node in tree.nodes.items():
        parent = node.parent_session or "(根)"
        print(f"  {sid} [{node.role_name}] ({node.display_name}) parent={parent} "
              f"children={len(node.children)}")
