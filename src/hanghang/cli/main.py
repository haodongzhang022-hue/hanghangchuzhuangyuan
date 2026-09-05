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

    result = router.route(args.text)
    plan = planner.plan(args.text)

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
    """M8 跨行业能力索引搜索"""
    registry = Registry()
    matches = registry.search_by_keyword(args.keyword)
    if not matches:
        print(f"未找到与 '{args.keyword}' 匹配的行业单元")
        return
    print(f"关键词 '{args.keyword}' 匹配到 {len(matches)} 个行业单元:")
    for u in matches:
        print(f"  - {u.unit_id} [{u.industry}] tags={u.capability_tags}")


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

        plan = planner.plan(args.text)
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

    s = sub.add_parser("search", help="按关键词搜索行业能力索引")
    s.add_argument("keyword", help="搜索关键词")
    s.set_defaults(func=cmd_search)

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

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
