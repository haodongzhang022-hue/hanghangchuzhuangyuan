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
    SessionBindingStore, SessionBoundRouter,
)
from hanghang.engine.coverage import CoverageTracker
from hanghang.cli.state_commands import (
    cmd_state_init, cmd_state_add, cmd_state_show,
    cmd_state_compact, cmd_state_update, cmd_state_fold,
    cmd_state_submit, cmd_state_list,
    cmd_state_claim, cmd_state_release, cmd_state_status,
    cmd_arb_list, cmd_arb_show, cmd_arb_review, cmd_arb_diff,
    cmd_state_search,
    cmd_state_archive, cmd_state_retrieve,
    cmd_state_refs, cmd_state_full,
    cmd_tree_init, cmd_tree_register, cmd_tree_link,
    cmd_tree_show, cmd_tree_rollup,
    cmd_tree_submit_chain, cmd_tree_list,
)

def cmd_route(args):
    """意图路由命令（支持 SLIB 会话级行业绑定）

    用法:
        python3 cli/main.py route "文本" [--session SESSION_ID]

    有 --session 时：
        - 若会话已绑定行业 X → 消息只能在 X 内路由
        - 若消息明显属于行业 Y(≠X) → 返回 cross_industry_handoff
        - 若会话未绑定 → 首次路由后自动绑定
    """
    registry = Registry()
    metrics = MetricsCollector()
    prefixes = PrefixArchive()
    bindings = SessionBindingStore()

    # 自动注册单元到前缀档案库
    for unit in registry.all_units():
        prefixes.register_unit(unit)

    session_id = getattr(args, "session", None) or None
    sbr = SessionBoundRouter(
        registry=registry,
        binding_store=bindings,
    )

    # SLIB 会话感知路由
    result = sbr.route(args.text, session_id=session_id)

    # 记录指标
    mode = result.get("mode", "manual")
    rr = result.get("route_result", {})
    plan = result.get("plan", {})
    unit_id = plan.get("unit_id", "") or rr.get("unit_id", "")
    metrics.record_route(
        mode=mode if mode != "cross_industry_handoff" else "handoff_required",
        unit_id=unit_id,
        roles=rr.get("roles", []),
    )

    print("=" * 50)
    print(f"意图: {args.text}")
    print(f"路由结果: unit={rr.get('unit_id') or 'N/A'}, "
          f"industry={rr.get('industry') or 'N/A'}, "
          f"roles={rr.get('roles') or '无'}")
    print(f"置信度: {rr.get('confidence', 0)}")

    if session_id:
        print(f"会话: {session_id}")

    if mode == "manual":
        print(f"模式: 人工确认 (原因: {plan.get('reason') or rr.get('fallback_reason', '')})")
    elif mode == "cross_industry_handoff":
        print(f"模式: ⚠️ SLIB 跨行业冲突（需开新会话）")
        print(f"  {result.get('message', '')}")
        if result.get("handoff_card_id"):
            print(f"  交接卡ID: {result['handoff_card_id']}")
    else:
        print(f"模式: {mode}")
        print(plan.get("message", ""))

    # 展示会话绑定信息
    if session_id and result.get("binding"):
        b = result["binding"]
        print(f"会话绑定: {b['industry']} ({b['unit_id']})")

    # 展示稳定前缀（若适用）
    if rr.get("unit_id") and mode in ("direct", "composite"):
        unit_prefixes = prefixes.get_unit_prefixes(rr["unit_id"])
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
    if result.get("handoff_card_id"):
        print(f"交接卡ID: {result['handoff_card_id']}")
    print("=" * 50)


def cmd_bind_session(args):
    """显式绑定会话到行业单元（SLIB）"""
    registry = Registry()
    # 验证 unit_id 存在
    unit = registry.get_unit(args.unit)
    if unit is None:
        print(f"错误: 行业单元 {args.unit} 不存在。可用单元: ")
        for u in registry.all_units():
            print(f"  {u.unit_id} ({u.industry})")
        return
    store = SessionBindingStore()
    try:
        b = store.bind(
            session_id=args.session,
            unit_id=args.unit,
            industry=unit.industry,
            role_name=getattr(args, "role", "") or "",
        )
        print(f"会话 {b.session_id} 已绑定到行业「{b.industry}」({b.unit_id})")
    except ValueError as e:
        print(f"绑定失败: {e}")


def cmd_unbind_session(args):
    """解除会话的行业绑定（SLIB）"""
    store = SessionBindingStore()
    b = store.get_binding(args.session)
    if b is None:
        print(f"会话 {args.session} 未绑定任何行业")
        return
    print(f"解除绑定: {b.session_id} ← {b.industry} ({b.unit_id})")
    store.unbind(args.session)
    print("已解除")


def cmd_list_bindings(args):
    """列出所有已绑定的会话"""
    store = SessionBindingStore()
    print(store.summary())


def cmd_binding_info(args):
    """查看会话的行业绑定详情"""
    store = SessionBindingStore()
    b = store.get_binding(args.session)
    if b is None:
        print(f"会话 {args.session} 未绑定任何行业")
        return
    print(f"会话: {b.session_id}")
    print(f"行业: {b.industry}")
    print(f"单元: {b.unit_id}")
    print(f"岗位: {b.role_name or '(未指定)'}")
    print(f"绑定时间: {b.bound_at}")
    print(f"最近路由: {b.updated_at}")


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
    rate = s['auto_success_rate']
    rate_str = f"{rate:.1%}" if rate is not None else "暂无数据"
    print(f"自动成功率: {rate_str}")
    print(f"直连: {s['direct_routes']}, 复合: {s['composite_routes']}, "
          f"交接: {s['handoffs']}, 人工: {s['manual_confirmations']}")
    print(f"单元命中: {s['unit_hits']}")
    print(f"岗位命中: {s['role_hits']}")



def cmd_coverage(args):
    """输出行业/岗位覆盖进度表(目标全集 vs 当前覆盖)"""
    tracker = CoverageTracker()
    if getattr(args, "gaps", False):
        gaps = tracker.gaps()
        if not gaps:
            print("目标全集行业均已覆盖，无待补缺口。")
            return
        print(f"待补缺口 {len(gaps)} 个目标行业(需通过各渠道搜集岗位并建单元补齐):")
        for g in gaps:
            roles = "、".join(g["roles"]["names"]) or "岗位待搜集"
            ch = "；".join(g["channels"]) if g["channels"] else "渠道待定"
            print(f"  - {g['name']} [{g['category']}] 优先级={g['priority']} 目标岗位: {roles}")
            print(f"      建议渠道: {ch}")
        return
    print(tracker.render_text())

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


# 延迟导入 serve（避免启动时 import http.server 影响 CLI 速度）
def cmd_serve(args):
    """启动 Web 可视化控制台"""
    from hanghang.web.server import serve_forever
    host = getattr(args, "host", "127.0.0.1")
    port = getattr(args, "port", 8080)
    serve_forever(host, port)


def build_parser():
    p = argparse.ArgumentParser(
        prog="hanghang",
        description="行行出状元 · 通用能力层路由编排系统")
    sub = p.add_subparsers(dest="command")

    r = sub.add_parser("route", help="对一句话意图做路由识别（支持 --session SLIB 会话绑定）")
    r.add_argument("text", help="用户意图文本")
    r.add_argument("--session", default="", help="会话ID（SLIB 会话级行业绑定）")
    r.set_defaults(func=cmd_route)

    l = sub.add_parser("units", help="列出已注册行业单元")
    l.set_defaults(func=cmd_units)

    # ---- SLIB 会话级行业绑定子命令 ----
    bind = sub.add_parser("bind", help="SLIB: 将会话绑定到行业单元")
    bind.add_argument("--session", required=True, help="会话ID")
    bind.add_argument("--unit", required=True, help="行业单元ID（如 dongjiagoushi）")
    bind.add_argument("--role", default="", help="岗位名（可选）")
    bind.set_defaults(func=cmd_bind_session)

    ubind = sub.add_parser("unbind", help="SLIB: 解除会话的行业绑定")
    ubind.add_argument("--session", required=True, help="会话ID")
    ubind.set_defaults(func=cmd_unbind_session)

    blist = sub.add_parser("bindings", help="SLIB: 列出所有已绑定的会话")
    blist.set_defaults(func=cmd_list_bindings)

    bshow = sub.add_parser("binding", help="SLIB: 查看会话的行业绑定详情")
    bshow.add_argument("--session", required=True, help="会话ID")
    bshow.set_defaults(func=cmd_binding_info)

    m = sub.add_parser("metrics", help="查看运行指标")
    m.set_defaults(func=cmd_metrics)

    s = sub.add_parser("search", help="按关键词多维搜索行业能力索引")
    s.add_argument("keyword", help="搜索关键词")
    s.add_argument("--mode", default="any",
                   choices=["any", "industry", "capability", "role"],
                   help="检索维度(默认any: 行业/能力/岗位全部)")
    s.set_defaults(func=cmd_search)


    cv = sub.add_parser("coverage", help="行业/岗位覆盖进度表(目标全集 vs 当前覆盖)")
    cv.add_argument("--gaps", action="store_true", help="仅列出待补缺口")
    cv.set_defaults(func=cmd_coverage)

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


    srv = sub.add_parser("serve", help="启动 Web 可视化聚合控制台")
    srv.add_argument("--host", default="127.0.0.1", help="监听地址(默认127.0.0.1)")
    srv.add_argument("--port", type=int, default=8080, help="监听端口(默认8080)")
    srv.set_defaults(func=cmd_serve)
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

    sarch = state_sub.add_parser("archive", help="归档一段原文全文到ContentArchive")
    sarch.add_argument("--session", required=True, help="会话ID")
    sarch.add_argument("--ref", required=True, help="原文引用(content_ref)")
    sarch.add_argument("--content", required=True, help="原文全文")
    sarch.add_argument("--title", default="", help="段标题")
    sarch.set_defaults(func=cmd_state_archive)

    sret = state_sub.add_parser("retrieve", help="按content_ref从归档取回原文全文")
    sret.add_argument("--session", required=True, help="会话ID")
    sret.add_argument("--ref", required=True, help="原文引用(content_ref)")
    sret.set_defaults(func=cmd_state_retrieve)

    srefs = state_sub.add_parser("refs", help="列出某会话全部已归档content_ref")
    srefs.add_argument("--session", required=True, help="会话ID")
    srefs.set_defaults(func=cmd_state_refs)

    sfull = state_sub.add_parser("full", help="展示可恢复完整视图(导航+原文归档)")
    sfull.add_argument("--session", required=True, help="会话ID")
    sfull.set_defaults(func=cmd_state_full)

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

    arbt = arb_sub.add_parser("diff", help="查看票据 A/B 双方字段级差异")
    arbt.add_argument("--ticket", required=True, help="票据ID")
    arbt.set_defaults(func=cmd_arb_diff)

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
        print("请指定 state 子命令：init / add / show / compact / update / fold / submit / list / claim / release / status / search")
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
