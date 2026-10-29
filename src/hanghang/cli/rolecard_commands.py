"""M11 岗位画像层 · CLI 子命令（role 组）

  role list      岗位就绪度表（哪些岗位能真上手、缺什么）
  role show      看一张岗位卡（六维评估全貌 + 就绪度）
  role playbook  取岗位工作流的分步 playbook（Agent 照着干 / 导出 n8n / 导出代码桩）
  role context   渲染可注入提示词的岗位卡文本块（M10 素材）
  role coverage  画像覆盖总览
  role chain     利益链条（只看行业类；公司靠索引现查，不落库）+ 校验
"""
from __future__ import annotations

import json
import sys
from typing import Optional

from hanghang.engine import Registry
from hanghang.rolecard import RoleCardStore


def _store() -> RoleCardStore:
    return RoleCardStore(registry=Registry())


def _resolve(store: RoleCardStore, role_name: str, unit_id: Optional[str] = None):
    """定位岗位卡：给了 --unit 就精确取，否则全局按岗位名找（重名返回多张）。"""
    if unit_id:
        return [c for c in [store.get(unit_id, role_name)] if c]
    return store.find_role(role_name)


def _fmt_list(values) -> str:
    return "、".join(str(v) for v in values) if values else "—"


# ------------------------------------------------------------------ role list
def cmd_role_list(args):
    store = _store()
    cards = store.all_cards()
    if getattr(args, "unit", None):
        cards = [c for c in cards if c.unit_id == args.unit]
    if not cards:
        print("未找到岗位画像卡；请检查 data/role-profiles/ 是否存在。")
        return 1

    print("=" * 78)
    print(f"{'就绪度':<7}{'评级':<5}{'岗位':<28}{'行业单元':<16}缺口")
    print("-" * 78)
    rows = sorted(cards, key=lambda c: (-(c.readiness.score if c.readiness else 0),
                                       c.unit_id, c.role))
    for c in rows:
        r = c.readiness
        score = f"{r.score:.1f}" if r else "0.0"
        grade = r.grade if r else "D"
        gap = r.gaps[0] if r and r.gaps else "—"
        if len(gap) > 26:
            gap = gap[:26] + "…"
        print(f"{score:<9}{grade:<6}{c.role:<28}{c.unit_id:<16}{gap}")
    summary = store.coverage_summary()
    print("-" * 78)
    print(f"岗位 {summary['total_roles']} / 有画像 {summary['profiled_roles']}"
          f" / 画像覆盖 {summary['profile_coverage'] * 100:.0f}%"
          f" / 就绪度均值 {summary['average_score']} / 评级 {summary['grades']}")
    return 0


# ------------------------------------------------------------------ role show
def cmd_role_show(args):
    store = _store()
    cards = _resolve(store, args.role, getattr(args, "unit", None))
    if not cards:
        print(f"未找到岗位: {args.role}")
        return 1
    for card in cards:
        p = card.profile
        print("=" * 70)
        print(f"岗位卡: {card.role}（{card.unit_id} / {card.industry}）  前缀 {card.prefix}")
        print(f"职责: {card.description or '—'}")
        if card.readiness:
            r = card.readiness
            print(f"就绪度: {r.score} [{r.grade}] {r.label}")
            print("  因子: " + "  ".join(f"{k}={v}" for k, v in r.factors.items()))
            if r.gaps:
                print("  缺口: " + "；".join(r.gaps))
        if not p:
            print("（该岗位尚无画像基线：仅能路由，无法按六维评估/工作流执行）")
            continue

        a = p.analysis
        print("\n① 岗位分析")
        print(f"  使命: {a.get('mission', '—')}")
        print(f"  交付物: {_fmt_list(a.get('deliverables'))}")
        print(f"  输入: {_fmt_list(a.get('inputs'))}")
        print(f"  产出: {_fmt_list(a.get('outputs'))}")
        print(f"  度量: {_fmt_list(a.get('kpis'))}")

        ps = p.persona
        print("\n② 岗位画像")
        print(f"  资历: {ps.get('seniority', '—')}")
        print(f"  心态: {ps.get('mindset', '—')}")
        print(f"  语气: {ps.get('tone', '—')}")
        print(f"  可决断: {_fmt_list(ps.get('decision_rights'))}")
        print(f"  边界: {_fmt_list(ps.get('constraints'))}")

        pl = p.plugin
        print("\n③ 插件封装")
        print(f"  包名: {pl.get('bundle', '—')}")
        print(f"  工具: {_fmt_list(pl.get('tools'))}")
        print(f"  MCP 类别: {_fmt_list(pl.get('mcp_categories'))}")
        for art in card.plugin_artifacts:
            print(f"  技能: {art.get('name')}  {art.get('path', '')}")

        print("\n④ 工作流")
        for wf in card.workflows:
            flag = " [default]" if wf.get("default") else ""
            print(f"  · {wf.get('name')}（{wf.get('id')} / 模板 {wf.get('template')}）{flag}")
            for i, step in enumerate(wf.get("steps", []) or [], 1):
                rt = step.get("runtime", "agent")
                print(f"      {i}. {step.get('name') or step.get('id')} [{rt}]")
                if step.get("playbook"):
                    print(f"         → {step['playbook']}")
                if step.get("outputs"):
                    print(f"         产出: {_fmt_list(step['outputs'])}")
                if step.get("verify"):
                    print(f"         验收: {_fmt_list(step['verify'])}")

        ch = p.stakeholders
        print("\n⑤ 利益链条")
        print(f"  上游: {_fmt_list(ch.upstream)}")
        print(f"  下游: {_fmt_list(ch.downstream)}")
        print(f"  受益方: {_fmt_list(ch.beneficiaries)}")
        print(f"  阻碍方: {_fmt_list(ch.blockers)}")
        print(f"  激励: {_fmt_list(ch.incentives)}")
        print(f"  风险: {_fmt_list(ch.risk_notes)}")

        cap = p.capability
        print("\n⑥ 核心能力")
        print(f"  能力: {_fmt_list(cap.core)}")
        print(f"  工具: {_fmt_list(cap.tools)}")
        print(f"  知识: {_fmt_list(cap.knowledge)}")
        print(f"  软技能: {_fmt_list(cap.soft)}")
        if cap.scoring:
            print("  评分: " + "  ".join(f"{k}={v}" for k, v in cap.scoring.items())
                  + f"  （均值 {cap.average_score()}/5）")
    return 0


# ------------------------------------------------------------------ role playbook
def cmd_role_playbook(args):
    store = _store()
    cards = _resolve(store, args.role, getattr(args, "unit", None))
    if not cards:
        print(f"未找到岗位: {args.role}")
        return 1
    card = cards[0]
    steps = card.playbook(args.workflow or "")
    if not steps:
        print(f"岗位 {card.role} 无可用工作流（请先补 data/role-profiles 的 workflow.templates）")
        return 1

    fmt = args.format
    if fmt == "json":
        payload = [s.__dict__ for s in steps]
        print(json.dumps({"role": card.role, "unit": card.unit_id,
                          "workflow": args.workflow or "default",
                          "steps": payload}, ensure_ascii=False, indent=2))
        return 0
    if fmt in ("n8n", "code"):
        # 可移植导出：只保留执行所需信息，不保存任何凭据/环境配置
        print(_export_skeleton(card, steps, fmt))
        return 0

    print(f"# 岗位 playbook: {card.role}（{card.unit_id}）")
    wf = card.workflow_by_id(args.workflow) if args.workflow else card.default_workflow()
    if wf:
        print(f"# 工作流: {wf.get('name')}  模板: {wf.get('template')}")
    for i, s in enumerate(steps, 1):
        print(f"\n[{i}/{len(steps)}] {s.name or s.id}  (runtime={s.runtime})")
        if s.preconditions:
            print(f"  前置: {_fmt_list(s.preconditions)}")
        if s.playbook:
            print(f"  做法: {s.playbook}")
        if s.outputs:
            print(f"  产出: {_fmt_list(s.outputs)}")
        if s.verify:
            print(f"  验收: {_fmt_list(s.verify)}")
    return 0


def _export_skeleton(card, steps, fmt: str) -> str:
    """把 playbook 导成 n8n 节点清单 / 纯代码桩（复用形态，不含凭据）。"""
    lines = []
    if fmt == "n8n":
        lines.append(f"# n8n 节点清单导出: {card.role}（{card.unit_id}）")
        lines.append("# 说明：节点类型只是建议映射，凭据一律走 n8n 凭据库，本文件不存密钥。")
        lines.append("nodes:")
        for i, s in enumerate(steps, 1):
            node_type = {"code": "code", "n8n": "httpRequest"}.get(s.runtime, "set")
            lines.append(f"  - name: \"{i}.{s.name or s.id}\"")
            lines.append(f"    type: n8n-nodes-base.{node_type}")
            lines.append(f"    params: {{ note: \"{s.playbook[:60]}\" }}")
        return "\n".join(lines)
    lines.append(f"\"\"\"岗位流程代码桩: {card.role}（{card.unit_id}）")
    lines.append("由 M11 playbook 导出；只给出工序骨架，业务实现留空。\"\"\"")
    lines.append("")
    lines.append("STEPS = [")
    for s in steps:
        lines.append(f"    dict(id={s.id!r}, name={s.name!r}, runtime={s.runtime!r},")
        lines.append(f"         outputs={s.outputs!r}, verify={s.verify!r}),")
    lines.append("]")
    lines.append("")
    lines.append("")
    lines.append("def run(payload: dict) -> dict:")
    lines.append("    ctx = dict(payload)")
    lines.append("    for step in STEPS:")
    lines.append("        # TODO: 实现 step['id'] 的业务逻辑（playbook 见 role show）")
    lines.append("        ctx[step['id']] = None")
    lines.append("    return ctx")
    return "\n".join(lines)


# ------------------------------------------------------------------ role context
def cmd_role_context(args):
    store = _store()
    cards = _resolve(store, args.role, getattr(args, "unit", None))
    if not cards:
        print(f"未找到岗位: {args.role}")
        return 1
    print(cards[0].to_context_block(args.workflow or ""))
    return 0


# ------------------------------------------------------------------ role coverage
def cmd_role_coverage(args):
    store = _store()
    summary = store.coverage_summary()
    print("=" * 60)
    print("M11 岗位画像覆盖")
    print(f"  岗位总数: {summary['total_roles']}")
    print(f"  有画像: {summary['profiled_roles']}"
          f"（{summary['profile_coverage'] * 100:.0f}%）")
    print(f"  就绪度均值: {summary['average_score']}")
    print(f"  评级分布: {summary['grades']}")
    if getattr(args, "gaps", False):
        print("\n待补岗位（无画像基线）:")
        for unit in store.registry.all_units():
            lack = [r.name for r in unit.roles if not (store.profiles.get(unit.unit_id) or {}).get(r.name)]
            if lack:
                print(f"  - {unit.unit_id}: {', '.join(lack)}")
    return 0


# ------------------------------------------------------------------ role chain
def cmd_role_chain(args):
    store = _store()
    classes = store.classes

    # --check：守门（链上写了公司 / 未登记类目 → 非 0 退出）
    if args.check:
        issues = store.chain_issues(args.unit or "", args.role or "")
        errors = [i for i in issues if i.level == "error"]
        warns = [i for i in issues if i.level == "warn"]
        for i in errors + warns:
            print(i)
        print(f"\n链条校验：error {len(errors)} / warn {len(warns)}"
              f" / 公司形态标记 {len(classes.company_markers)} 个")
        if errors:
            print("链上只写行业类目；具体公司靠 index 现查，不进画像。")
            return 1
        return 0

    # --class：类目 → 引用它的岗位 + 索引方案（类落到列表和索引的那份列表）
    if args.class_name:
        usage = store.class_usage()
        key = classes.canonical(args.class_name)
        if key not in usage:
            if classes.has_class(key):
                spec = classes.classes.get(key) or {}
                print(f"行业类: {key}  [{spec.get('kind', '')}]")
                idx = spec.get("index")
                print(f"  索引: {idx.get('source')} → {'; '.join(idx.get('query') or [])}"
                      if idx else "  索引: 未接（index: null）")
                print("  被引用: 0 处（已登记，当前没有岗位用它）")
                return 0
            print(f"类目「{args.class_name}」未登记"
                  f"（先在 data/industry-classes.yaml 登记，再在岗位链条上引用）")
            return 1
        item = usage[key]
        print(f"行业类: {item['class']}  [{item['kind']}]")
        idx = item.get("index")
        if idx:
            print(f"  索引: {idx.get('source')} → {'; '.join(idx.get('query') or [])}")
            print("  说明: 只存检索方式，不存公司名录")
        else:
            print("  索引: 未接（index: null）")
        print(f"  被引用: {len(item['used_by'])} 处")
        for u in item["used_by"]:
            print(f"    - {u['unit']}/{u['role']}.{u['field']}")
        return 0

    # 默认：看某岗位的链条归一结果
    if not args.role:
        print("用法: role chain <岗位名> [--unit X] | role chain --check | role chain --class 钢材加工")
        return 1

    cards = _resolve(store, args.role, args.unit or None)
    if not cards:
        print(f"未找到岗位: {args.role}")
        return 1
    card = cards[0]
    print(f"利益链条: {card.role}（{card.unit_id} / {card.industry}）")
    labels = {"upstream": "上游", "downstream": "下游",
              "beneficiaries": "受益方", "blockers": "阻碍方"}
    for field, label in labels.items():
        entries = (card.chain_refs or {}).get(field) or []
        print(f"\n{label}（{len(entries)}）")
        if not entries:
            print("  —")
            continue
        for e in entries:
            kind = e.get("kind", "")
            tail = ""
            if kind == "role":
                tail = f"岗位 → {e.get('unit') or card.unit_id}"
            elif e.get("index"):
                tail = f"索引 → {e['index'].get('source')}"
            elif kind == "industry_class":
                tail = "未接索引"
            print(f"  · {e.get('value')}  [{kind}]"
                  + (f"  {tail}" if tail else "")
                  + ("" if e.get("raw") == e.get("value")
                     else f"  （原文「{e.get('raw')}」已归一）"))
    issues = store.chain_issues(card.unit_id, card.role)
    if issues:
        print("\n校验:")
        for i in issues:
            print(f"  {i}")
    else:
        print("\n校验: ✅ 无公司名、无未登记类目")
    return 0


def register_role_subcommands(sub) -> None:
    """把 role 组挂到主 parser（保持 main.py 组织简洁）。"""
    rp = sub.add_parser("role", help="M11 岗位画像：就绪度/六维评估/工作流 playbook")
    role_sub = rp.add_subparsers(dest="role_cmd")

    rl = role_sub.add_parser("list", help="岗位就绪度表")
    rl.add_argument("--unit", default="", help="只看某个行业单元")
    rl.set_defaults(func=cmd_role_list)

    rs = role_sub.add_parser("show", help="看岗位卡全貌（六维评估+就绪度）")
    rs.add_argument("role", help="岗位名，如 architect")
    rs.add_argument("--unit", default="", help="行业单元（岗位重名时必填）")
    rs.set_defaults(func=cmd_role_show)

    rp2 = role_sub.add_parser("playbook", help="取岗位工作流的分步 playbook")
    rp2.add_argument("role", help="岗位名")
    rp2.add_argument("--unit", default="", help="行业单元")
    rp2.add_argument("--workflow", default="", help="工作流 id（默认取 default 流）")
    rp2.add_argument("--format", default="text",
                     choices=["text", "json", "n8n", "code"],
                     help="输出形态：text 人读 / json / n8n 节点清单 / code 代码桩")
    rp2.set_defaults(func=cmd_role_playbook)

    rc = role_sub.add_parser("context", help="渲染可注入提示词的岗位卡文本块")
    rc.add_argument("role", help="岗位名")
    rc.add_argument("--unit", default="", help="行业单元")
    rc.add_argument("--workflow", default="", help="指定工作流 id")
    rc.set_defaults(func=cmd_role_context)

    rch = role_sub.add_parser("chain", help="利益链条：行业类归一 + 校验（公司不落库）")
    rch.add_argument("role", nargs="?", default="", help="岗位名（不给则只看 --check/--class）")
    rch.add_argument("--unit", default="", help="行业单元")
    rch.add_argument("--check", action="store_true",
                     help="校验全量链条：公司形态/未登记类目 → 失败")
    rch.add_argument("--class", dest="class_name", default="",
                     help="查某个行业类被哪些岗位引用、怎么检索")
    rch.set_defaults(func=cmd_role_chain)

    rv = role_sub.add_parser("coverage", help="岗位画像覆盖总览")
    rv.add_argument("--gaps", action="store_true", help="列出缺画像的岗位")
    rv.set_defaults(func=cmd_role_coverage)

    rp.set_defaults(func=lambda a: (rp.print_help(), 0)[1])
