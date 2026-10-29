#!/usr/bin/env python3
"""M11 岗位画像卡渲染器

把三份数据合成可执行的岗位卡，落盘到 data/rolecards/<unit_id>.yaml：
  1) 画像基线   data/role-profiles/<unit_id>.yaml   （人写，六维评估）
  2) 注册表     data/industry-register.yaml 等      （岗位事实：名/前缀/关键词）
  3) 工作流模板 data/workflow-templates/*.yaml       （通用工序 + 岗位覆盖）
  4) 上游技能包 vendor/upstream/knowledge-work-plugins（可选，--from-kwp）

为什么要落盘：渲染结果要能被 review、能被 diff、能被别的 runtime（n8n/纯代码）
直接读，而不是每次启动现算一份飘忽的东西。

用法：
  python3 scripts/gen_rolecards.py                          # 渲染全部有画像的单元
  python3 scripts/gen_rolecards.py --unit dongjiagoushi      # 只渲一个单元
  python3 scripts/gen_rolecards.py --from-kwp vendor/upstream/knowledge-work-plugins
  python3 scripts/gen_rolecards.py --check                   # 只校验未过期，不写盘（CI 用）
  python3 scripts/gen_rolecards.py --readiness               # 打印就绪度总览
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
from typing import Dict, List

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../src"))

from hanghang.rolecard import RoleCardStore          # noqa: E402
from hanghang.rolecard.models import RoleCard       # noqa: E402

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
HEADER = (
    "# ⚠️ 本文件由 scripts/gen_rolecards.py 生成，请勿手改。\n"
    "# 改画像请编辑 data/role-profiles/，改工序请编辑 data/workflow-templates/。\n"
)


# ---------------------------------------------------------------- 上游技能包
def load_kwp_skills(kwp_dir: str) -> Dict[str, List[dict]]:
    """扫描上游 knowledge-work-plugins 快照，按插件名收集技能清单。

    只读 SKILL.md 的 YAML frontmatter（name/description），不执行、不加载任何
    上游 .mcp.json 或命令定义——上游在本仓库里只是"技能包装形态"的参考数据。
    """
    out: Dict[str, List[dict]] = {}
    if not kwp_dir or not os.path.isdir(kwp_dir):
        return out
    for plugin_dir in sorted(glob.glob(os.path.join(kwp_dir, "*"))):
        if not os.path.isdir(plugin_dir):
            continue
        skills_dir = os.path.join(plugin_dir, "skills")
        if not os.path.isdir(skills_dir):
            continue
        plugin = os.path.basename(plugin_dir)
        items = []
        for skill_md in sorted(glob.glob(os.path.join(skills_dir, "*", "SKILL.md"))):
            meta = _frontmatter(skill_md)
            rel = os.path.relpath(skill_md, REPO_ROOT)
            items.append({
                "name": meta.get("name") or os.path.basename(os.path.dirname(skill_md)),
                "kind": "skill",
                "path": rel,
                "description": (meta.get("description") or "")[:200],
            })
        if items:
            out[plugin] = items
    return out


def _frontmatter(path: str) -> dict:
    """读 markdown 头部 --- 之间的 YAML（同 Claude skill 约定）。"""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.read().split("\n")
    except OSError:
        return {}
    if not lines or lines[0].strip() != "---":
        return {}
    body = []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        body.append(line)
    try:
        return yaml.safe_load("\n".join(body)) or {}
    except yaml.YAMLError:
        return {}


# ---------------------------------------------------------------- 渲染
def card_to_dict(card: RoleCard) -> dict:
    p = card.profile
    data = {
        "role": card.role,
        "unit_id": card.unit_id,
        "industry": card.industry,
        "prefix": card.prefix,
        "description": card.description,
        "keywords": card.keywords,
        "readiness": card.readiness.to_dict() if card.readiness else {},
        "activation": card.activation,
        "six_dims": {},
        "workflows": card.workflows,
        "plugin_artifacts": card.plugin_artifacts,
        "sources": card.sources,
        # M11.1 归一后的链条引用（行业类 + index / 岗位 + unit），与六维原始字符串并列落盘
        "chain_refs": card.chain_refs,
    }
    if p:
        data["six_dims"] = {
            "analysis": p.analysis,
            "persona": p.persona,
            "plugin": p.plugin,
            "workflow": p.workflow,
            "stakeholders": {
                "upstream": p.stakeholders.upstream,
                "downstream": p.stakeholders.downstream,
                "beneficiaries": p.stakeholders.beneficiaries,
                "blockers": p.stakeholders.blockers,
                "incentives": p.stakeholders.incentives,
                "risk_notes": p.stakeholders.risk_notes,
            },
            "capability": {
                "core": p.capability.core,
                "tools": p.capability.tools,
                "knowledge": p.capability.knowledge,
                "soft": p.capability.soft,
                "scoring": p.capability.scoring,
            },
        }
    return data


def attach_upstream_artifacts(card: RoleCard, kwp: Dict[str, List[dict]],
                              profile_plugin: str) -> None:
    """把上游对应插件的技能清单并入 plugin_artifacts（去重，保留我方声明的在前）。"""
    extra = kwp.get(profile_plugin) if profile_plugin else None
    if not extra:
        return
    seen = {a.get("name") for a in card.plugin_artifacts}
    for item in extra:
        if item["name"] in seen:
            continue
        card.plugin_artifacts.append(item)
        seen.add(item["name"])


def render_unit(store: RoleCardStore, unit_id: str, kwp: Dict[str, List[dict]],
                kwp_plugin_map: Dict[str, str]) -> dict:
    cards = store.cards_for_unit(unit_id)
    for card in cards:
        plugin_key = kwp_plugin_map.get(card.role, "")
        if not plugin_key and card.profile:
            plugin_key = str((card.profile.plugin or {}).get("upstream_plugin", "") or "")
        attach_upstream_artifacts(card, kwp, plugin_key)
        store.scorer.score(card)  # 技能包并入后重算就绪度
    return {
        "unit_id": unit_id,
        "industry": cards[0].industry if cards else "",
        "generated_by": "scripts/gen_rolecards.py",
        "roles": [card_to_dict(c) for c in cards],
    }


# ---------------------------------------------------------------- MRI 输出
def print_readiness(store: RoleCardStore) -> None:
    summary = store.coverage_summary()
    print(f"岗位总数 {summary['total_roles']} / 有画像 {summary['profiled_roles']}"
          f" （覆盖 {summary['profile_coverage'] * 100:.0f}%）"
          f" / 平均就绪度 {summary['average_score']}")
    print("评级分布:", summary["grades"])
    rows = []
    for card in store.all_cards():
        r = card.readiness
        rows.append((r.score if r else 0.0, card.unit_id, card.role,
                     r.grade if r else "D", (r.gaps[0] if r and r.gaps else "")))
    for score, uid, role, grade, gap in sorted(rows, reverse=True):
        print(f"  {score:5.1f} {grade} {uid}/{role:<20} {gap}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="渲染 M11 岗位画像卡")
    ap.add_argument("--unit", action="append", default=[], help="只渲染指定 unit_id（可多次）")
    ap.add_argument("--from-kwp", default="", help="上游 knowledge-work-plugins 快照目录")
    ap.add_argument("--out", default="", help="输出目录（默认 data/rolecards）")
    ap.add_argument("--check", action="store_true", help="只校验已生成的卡是否过期（CI 用）")
    ap.add_argument("--readiness", action="store_true", help="打印就绪度总览后退出")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    store = RoleCardStore()

    if args.readiness:
        print_readiness(store)
        return 0

    out_dir = args.out or os.path.join(store.data_dir, "rolecards")
    os.makedirs(out_dir, exist_ok=True)
    kwp = load_kwp_skills(args.from_kwp) if args.from_kwp else {}
    unit_ids = args.unit or sorted(store.profiles.keys())

    stale: List[str] = []
    for unit_id in unit_ids:
        if unit_id not in store.profiles:
            print(f"跳过 {unit_id}：无画像基线 data/role-profiles/{unit_id}.yaml",
                  file=sys.stderr)
            continue
        payload = render_unit(store, unit_id, kwp, {})
        text = HEADER + yaml.safe_dump(payload, allow_unicode=True, sort_keys=False,
                                       width=100)
        path = os.path.join(out_dir, f"{unit_id}.yaml")
        if args.check:
            current = ""
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as fh:
                    current = fh.read()
            if current != text:
                stale.append(path)
            continue
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        if not args.quiet:
            scores = [r["readiness"].get("score", 0) for r in payload["roles"]]
            print(f"  ✅ {unit_id}: {len(payload['roles'])} 岗位"
                  f" 就绪度均值 {sum(scores) / len(scores):.1f}" if scores else "  ✅")
    if args.check:
        if stale:
            print("以下岗位卡已过期，请重跑 scripts/gen_rolecards.py：", file=sys.stderr)
            for p in stale:
                print(f"  - {p}", file=sys.stderr)
            return 1
        if not args.quiet:
            print("岗位卡均为最新")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
