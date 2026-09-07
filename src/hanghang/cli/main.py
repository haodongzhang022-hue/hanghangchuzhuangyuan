"""命令行入口"""
from __future__ import annotations

import argparse
import os
import sys

# 确保可导入 engine 模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from hanghang.engine import (
    Registry, IntentRouter, CompositePlanner, HandoffBus,
    MetricsCollector, PrefixArchive,
)
from hanghang.cli.state_commands import (
    cmd_state_init, cmd_state_add, cmd_state_show,
    cmd_state_compact, cmd_state_update, cmd_state_fold,
    cmd_state_submit, cmd_state_list,
    cmd_state_claim, cmd_state_release, cmd_state_status,
    cmd_arb_list, cmd_arb_show, cmd_arb_review, cmd_arb_test_diff,
    cmd_state_search,
    cmd_tree_init, cmd_tree_register, cmd_tree_link,
    cmd_tree_show, cmd_tree_rollup,
    cmd_tree_submit_chain, cmd_tree_list,
)


def cmd_route(args):
    """意图路由命令"""
    registry = Registry()
    router = IntentRouter(registry)
    planner = CompositePlanner(registry)
    metrics = MetricsCollector()
    prefixes = PrefixArchive()

    # 自动注册单元到前缀档案库
    for unit in registry.all_units():
        prefixes.register_unit(unit)

    # 仅路由一次：route() 结果既用于展示，也交由 plan_from_result 编排，
    # 避免与 planner.plan()（内部会再次 route）重复做意图识别。
    result = router.route(args.text)
    plan = planner.plan_from_result(result, args.text)

    # 记录指标
    metrics.record_route(
        mode=plan.get("mode", "manual"),
        unit_id=plan.get("unit_id", ""),
        roles=plan.get("roles", []),
    )

    print("=" * 50)
    print(f"意图: {args.text}")
    print(f"路由结果: unit={result.unit_id or 'N/A'}, industry={result.industry or 'N/A'}, "
          f"roles={result.roles or '无'}")
    print(f"置信度: {result.confidence}")

    if plan["mode"] == "manual":
        print(f"模式: 人工确认 (原因: {plan['reason']})")
    else:
        print(f"模式: {plan['mode']}")
        print(plan.get("message", ""))

    # 展示稳定前缀（若适用）
    if result.unit_id and plan["mode"] in ("direct", "composite"):
        unit_prefixes = prefixes.get_unit_prefixes(result.unit_id)
        if unit_prefixes:
            print(f"M3 前缀档案: {unit_prefixes}")

    if "session_prefix" in plan:
        print(f"会话前缀: {plan['session_prefix']}")
    if "session_prefix_set" in plan:
        print(f"稳定前缀集: {plan['session_prefix_set']}")
    if "execution_order" in plan:
        print(f"执行顺序: {plan['execution_order']}")
    if "boundary" in plan:
        print(f"复合边界规则: {plan['boundary']}")
    if "handoff_card_id" in plan and plan["handoff_card_id"]:
        print(f"交接卡ID: {plan['handoff_card_id']}")
    print("=" * 50)


def cmd_units(args):
    """列出已注册行业单元"""
    registry = Registry()
    prefixes = PrefixArchive()
    for unit in registry.all_units():
        prefixes.register_unit(unit)

    print(registry.summary())
    print("\n前缀档案:")
    print(prefixes.summary())


def cmd_metrics(args):
    """查看运行指标"""
    metrics = MetricsCollector()
    s = metrics.get_summary()
    print(f"总路由数: {s['total_routes']}")
    print(f"自动成功率: {s['auto_success_rate']:.1%}")
    print(f"直连: {s['direct_routes']}, 复合: {s['composite_routes']}, "
          f"交接: {s['handoffs']}, 人工: {s['manual_confirmations']}")
    print(f"单元命中: {s['unit_hits']}")
    print(f"岗位命中: {s['role_hits']}")


def cmd_search(args):
    """M8 跨行业能力索引多维搜索"""
    registry = Registry()
    mode = getattr(args, "mode", "any") or "any"
    matches = registry.search_capability(args.keyword, mode=mode)
    if not matches:
        print(f"未找到与 '{args.keyword}' 匹配的行业能力 [{mode} 维度]")
        return
    print(f"关键词 '{args.keyword}' 匹配 {len(matches)} 个行业能力 [{mode} 维度]:")
    for m in matches:
        detail = []
        if m["hit_roles"]:
            detail.append("岗位=" + ",".join(m["hit_roles"]))
        if m["hit_tags"]:
            detail.append("能力=" + ",".join(m["hit_tags"]))
        route = f"route@{m['entry_ref']}" if m["entry_ref"] else "本仓集中(待回填)"
        print(f"  - {m['unit_id']} [{m['industry']}] 命中维度={'/'.join(m['hit_kinds'])} "
              f"{' '.join(detail) if detail else ''} | {route}")
        if m["matched_terms"]:
            print(f"      命中词: {m['matched_terms']}")


def cmd_index(args):
    """M8 全量能力索引导出（供上层编排/可视化聚合）"""
    registry = Registry()
    index = registry.capability_index()
    print(f"能力索引共 {len(index)} 个行业单元:")
    for item in index:
        print(f"\n■ {item['unit_id']} [{item['industry']}]"
              f"{'  entry=' + item['entry_ref'] if item['entry_ref'] else '  本仓集中(待回填)'}")
        print("  能力标签:", ", ".join(item["capability_tags"]))
        role_lines = []
        for role in item["roles"]:
            flag = "复合" if role["composite"] else "不可复合"
            role_lines.append(f"{role['prefix']}{role['name']}({flag})")
        print("  岗位:", ", ".join(role_lines))


def cmd_create_handoff(args):
    """创建跨单元交接卡"""
    bus = HandoffBus()
    card = bus.create_handoff(
        source_unit=args.source,
        target_unit=args.target,
        intent=args.intent,
        context=args.context,
    )
    print(f"交接卡已创建: {card.source_unit} → {card.target_unit}")
    print(f"意图: {card.intent}")
    print(f"ID: {card.id}")


def cmd_list_handoffs(args):
    """列出待处理交接卡"""
    bus = HandoffBus()
    pending = bus.list_pending()
    if not pending:
        print("无待处理交接卡")
    for c in pending:
        print(f"  {c.source_unit} → {c.target_unit}: {c.intent} (status={c.status})")


def cmd_cross_unit(args):
    """跨单元交接编排：输入一句话意图，检测是否涉及多个行业单元"""
    registry = Registry()
    router = IntentRouter(registry)
    planner = CompositePlanner(registry)

    # 先检测是否存在"真跨行业"诉求（各单元持有独立信号）
    candidates = router.cross_unit_candidates(args.text)

    # 仅命中一个（含伪歧义：如共享泛化词"开发"）→ 走正常单行业路由
    if len(candidates) <= 1:
        result = router.route(args.text)
        print(f"路由结果: unit={result.unit_id or 'N/A'}")

        if result.needs_manual:
            print(f"需人工确认: {result.fallback_reason}")
            return

        unit = registry.get_unit(result.unit_id) if result.unit_id else None
        if not unit:
            print("无可用单元")
            return

        # 复用上面已算好的 route 结果，避免 planner.plan() 二次识别同一意图
        plan = planner.plan_from_result(result, args.text)
        print(f"单行业路由: {plan.get('mode', '')} — {plan.get('message', '')}")
        return

    # 真跨行业诉求（≥2 个独立行业信号命中）→ 触发交接编排
    unit_scores = router._score_units(args.text, registry.all_units())
    hits = [(uid, sc["score"]) for uid, sc in unit_scores.items()
            if uid in candidates and sc["score"] > 0]
    hits.sort(key=lambda x: x[1], reverse=True)

    print(f"检测到 {len(hits)} 个行业单元独立命中:")
    for uid, score in hits:
        u = registry.get_unit(uid)
        print(f"  - {uid} [{u.industry if u else ''}] score={score}")

    source = registry.get_unit(hits[0][0])
    target = registry.get_unit(hits[1][0])
    if source and target:
        plan = planner.plan_cross_unit(args.text, source.unit_id, target.unit_id)
        print(f"\n跨单元交接: {plan.get('message', '')}")
        if plan.get("handoff_card_id"):
            print(f"交接卡ID: {plan['handoff_card_id']}")


def build_parser():
    p = argparse.ArgumentParser(
        prog="hanghang",
        description="行行出状元 · 通用能力层路由编排系统")
    sub = p.add_subparsers(dest="command")

    r = sub.add_parser("route", help="对一句话意图做路由识别")
    r.add_argument("text", help="用户意图文本")
    r.set_defaults(func=cmd_route)

    l = sub.add_parser("units", help="列出已注册行业单元")
    l.set_defaults(func=cmd_units)

    m = sub.add_parser("metrics", help="查看运行指标")
    m.set_defaults(func=cmd_metrics)

    s = sub.add_parser("search", help="按关键词多维搜索行业能力索引")
    s.add_argument("keyword", help="搜索关键词")
    s.add_argument("--mode", default="any",
                   choices=["any", "industry", "capability", "role"],
                   help="检索维度(默认any: 行业/能力/岗位全部)")
    s.set_defaults(func=cmd_search)

    ci = sub.add_parser("index", help="导出全量跨行业能力索引")
    ci.set_defaults(func=cmd_index)

    h = sub.add_parser("handoff", help="创建交接卡")
    h.add_argument("--source", required=True, help="源单元")
    h.add_argument("--target", required=True, help="目标单元")
    h.add_argument("--intent", required=True, help="交接意图")
    h.add_argument("--context", default="", help="交接上下文")
    h.set_defaults(func=cmd_create_handoff)

    hp = sub.add_parser("handoffs", help="列出待处理交接卡")
    hp.set_defaults(func=cmd_list_handoffs)

    x = sub.add_parser("cross-unit", help="检测跨行业诉求并编排交接")
    x.add_argument("text", help="用户意图文本")
    x.set_defaults(func=cmd_cross_unit)

    # ---- M9 状态管理子命令 ----
    st = sub.add_parser("state", help="M9 状态管理：任务状态卡/折叠/层级提交")
    state_sub = st.add_subparsers(dest="state_cmd")

    si = state_sub.add_parser("init", help="初始化一张 StateCard")
    si.add_argument("--session", required=True, help="会话ID")
    si.add_argument("--objective", default="", help="总体目标")
    si.add_argument("--unit", default="", help="行业单元ID")
    si.add_argument("--role", default="secretary", help="维护者坑位名")
    si.set_defaults(func=cmd_state_init)

    sa = state_sub.add_parser("add", help="向 StateCard 添加任务")
    sa.add_argument("--session", required=True, help="会话ID")
    sa.add_argument("--title", required=True, help="任务标题")
    sa.add_argument("--objective", default="", help="任务目标")
    sa.add_argument("--files", default="", help="涉及文件，逗号分隔")
    sa.add_argument("--tools", default="", help="调取工具，逗号分隔")
    sa.add_argument("--type", default="normal",
                    choices=["normal", "deliverable"], help="任务类型")
    sa.set_defaults(func=cmd_state_add)

    ss = state_sub.add_parser("show", help="查看 StateCard 导航/渲染层")
    ss.add_argument("--session", required=True, help="会话ID")
    ss.set_defaults(func=cmd_state_show)

    sc = state_sub.add_parser("compact", help="生成压缩上下文")
    sc.add_argument("--session", required=True, help="会话ID")
    sc.set_defaults(func=cmd_state_compact)

    su = state_sub.add_parser("update", help="更新任务状态")
    su.add_argument("--session", required=True, help="会话ID")
    su.add_argument("--task", required=True, help="任务编号")
    su.add_argument("--state", required=True,
                    choices=["todo", "in_progress", "done", "blocked", "failed"],
                    help="目标状态")
    su.set_defaults(func=cmd_state_update)

    sf = state_sub.add_parser("fold", help="应用折叠策略")
    sf.add_argument("--session", required=True, help="会话ID")
    sf.set_defaults(func=cmd_state_fold)

    sm = state_sub.add_parser("submit", help="向上级提交汇总状态")
    sm.add_argument("--session", required=True, help="会话ID")
    sm.add_argument("--upstream", default="", help="上级会话ID")
    sm.set_defaults(func=cmd_state_submit)

    sl = state_sub.add_parser("list", help="列出所有 StateCard")
    sl.set_defaults(func=cmd_state_list)

    scl = state_sub.add_parser("claim", help="秘书声明对 StateCard 的归属/占用")
    scl.add_argument("--session", required=True, help="会话ID")
    scl.add_argument("--role", help="秘书坑位名(默认 secretary)")
    scl.add_argument("--force", action="store_true", help="强制抢占他人占用")
    scl.set_defaults(func=cmd_state_claim)
    srl = state_sub.add_parser("release", help="释放对 StateCard 的归属")
    srl.add_argument("--session", required=True, help="会话ID")
    srl.add_argument("--role", help="秘书坑位名(默认 secretary)")
    srl.set_defaults(func=cmd_state_release)
    sst = state_sub.add_parser("status", help="查看 StateCard 归属与版本状态")
    sst.add_argument("--session", required=True, help="会话ID")
    sst.add_argument("--role", help="秘书坑位名(默认 secretary)")
    sst.set_defaults(func=cmd_state_status)

    ssr = state_sub.add_parser("search", help="在StateCard中搜索任务（M8跨会话检索）")
    ssr.add_argument("--keyword", required=True, help="搜索关键词")
    ssr.set_defaults(func=cmd_state_search)



    # ---- M9+ 冲突仲裁子命令 ----
    arb = sub.add_parser("arb", help="M9+ 版本化冲突仲裁与审核")
    arb_sub = arb.add_subparsers(dest="arb_cmd")

    arbl = arb_sub.add_parser("list", help="列出冲突票据")
    arbl.add_argument("--session", default="", help="按会话过滤")
    arbl.add_argument("--status", default="", help="按状态过滤")
    arbl.set_defaults(func=cmd_arb_list)

    arbs = arb_sub.add_parser("show", help="查看冲突票据详情")
    arbs.add_argument("--ticket", required=True, help="票据ID")
    arbs.set_defaults(func=cmd_arb_show)

    arbr = arb_sub.add_parser("review", help="执行审核决策")
    arbr.add_argument("--ticket", required=True, help="票据ID")
    arbr.add_argument("--decision", required=True,
                       choices=["keep_a", "keep_b", "merge", "reject"],
                       help="keep_a=保留已提交版本, keep_b=保留冲突版本, merge=自动合并, reject=拒绝冲突修改")
    arbr.add_argument("--resolver", default="", help="审核者名")
    arbr.add_argument("--reason", default="", help="决策理由")
    arbr.set_defaults(func=cmd_arb_review)

    arbt = arb_sub.add_parser("diff", help="查看状态差异分析工具用法")
    arbt.add_argument("--session", default="", help="会话ID")
    arbt.set_defaults(func=cmd_arb_test_diff)

    # ---- M9 秘书长多级树子命令 ----
    stree = sub.add_parser("tree", help="M9 秘书长多级树：树拓扑管理/汇总/导航")
    tree_sub = stree.add_subparsers(dest="tree_cmd")

    ti = tree_sub.add_parser("init", help="初始化一棵秘书树")
    ti.add_argument("--name", default="default", help="树名称")
    ti.add_argument("--root", default="", help="根节点会话ID（默认用树名）")
    ti.add_argument("--role", default="secretary", help="根角色")
    ti.add_argument("--display", default="", help="根显示名")
    ti.add_argument("--objective", default="", help="根目标")
    ti.set_defaults(func=cmd_tree_init)

    tr = tree_sub.add_parser("register", help="注册一个节点到树")
    tr.add_argument("--name", default="default", help="树名称")
    tr.add_argument("--session", required=True, help="节点会话ID")
    tr.add_argument("--role", default="secretary", help="节点角色")
    tr.add_argument("--display", default="", help="节点显示名")
    tr.add_argument("--objective", default="", help="节点目标")
    tr.add_argument("--parent", default="", help="父节点会话ID")
    tr.set_defaults(func=cmd_tree_register)

    tl = tree_sub.add_parser("link", help="建立父子关系")
    tl.add_argument("--name", default="default", help="树名称")
    tl.add_argument("--parent", required=True, help="父节点会话ID")
    tl.add_argument("--child", required=True, help="子节点会话ID")
    tl.set_defaults(func=cmd_tree_link)

    ts = tree_sub.add_parser("show", help="渲染树导航视图")
    ts.add_argument("--name", default="default", help="树名称")
    ts.set_defaults(func=cmd_tree_show)

    trp = tree_sub.add_parser("rollup", help="整棵树逐级汇总")
    trp.add_argument("--name", default="default", help="树名称")
    trp.set_defaults(func=cmd_tree_rollup)

    tsc = tree_sub.add_parser("submit-chain", help="沿路径逐级向上提交")
    tsc.add_argument("--name", default="default", help="树名称")
    tsc.add_argument("--session", required=True, help="起始会话ID")
    tsc.set_defaults(func=cmd_tree_submit_chain)

    tlst = tree_sub.add_parser("list", help="列出所有节点")
    tlst.add_argument("--name", default="default", help="树名称")
    tlst.set_defaults(func=cmd_tree_list)

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)
    # state 子命令需要检查二级命令
    if args.command == "state" and not getattr(args, "state_cmd", None):
        print("请指定 state 子命令：init / add / show / compact / update / fold / submit / list / claim / release / status")
        print("请指定 arb 子命令：list / show / review / diff")
        print("示例: python3 src/hanghang/cli/main.py state init --session demo")
        sys.exit(1)
    if args.command == "arb" and not getattr(args, "arb_cmd", None):
        print("请指定 arb 子命令：list / show / review / diff")
        print("示例: python3 src/hanghang/cli/main.py arb list")
        sys.exit(1)
    if args.command == "tree" and not getattr(args, "tree_cmd", None):
        print("请指定 tree 子命令：init / register / link / show / rollup / submit-chain / list")
        print("示例: python3 src/hanghang/cli/main.py tree init --name project")
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
