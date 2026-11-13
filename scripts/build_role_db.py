#!/usr/bin/env python3
"""把岗位画像 + 行业词表落成**真库**（SQLite），并导出两种方言的 DDL。

前面的 `export_class_db.py` 只产 SQL 文本 —— 那是图纸。这个脚本建房子：
``data/db/hanghang.db`` 能直接用 sqlite3 / DB Browser / pandas 打开，25 张表能 join。

用法：
  python3 scripts/build_role_db.py                # 重建库 + 导 DDL + 打行数
  python3 scripts/build_role_db.py --check        # 库/DDL 是否与数据一致（CI 用）
  python3 scripts/build_role_db.py --stats        # 库里有什么
  python3 scripts/build_role_db.py --query "SQL"  # 只读查询（库要能被真用）

一致性口径（--check）：库里读回来重新渲染，必须与内存里的画像卡**逐字段相同**。
所以「改了画像忘记重建库」会被拦下，库不会静默和仓库分叉。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../src"))

from hanghang.rolecard import RoleCardStore, dbstore, schema_sql   # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DB_PATH = os.path.join(ROOT, dbstore.DEFAULT_DB_PATH)
DDL_SQLITE = os.path.join(ROOT, "data", "db", "00-schema.sqlite.sql")
DDL_PG = os.path.join(ROOT, "data", "db", "00-schema.postgresql.sql")
HEADER = "-- ⚠️ 本文件由 scripts/build_role_db.py 生成，请勿手改。\n"

# 逐字段比对的维度（读回来的卡 vs 内存里的卡）
_COMPARE = ("prefix", "description", "keywords", "workflows", "chain_refs",
            "plugin_artifacts", "readiness")


# 有序列表 / 键顺序在库里天然会变，比对前统一规范化
_ORDERED = ("keywords",)
_SORT_LISTS = True


# 库里空值就是「没有这一行」，读回来会补成空串/空表；比对时两边同等对待
_EMPTY = ("", None, [], {})


def _drop_empty(value):
    if not isinstance(value, dict):
        return value
    return {k: _drop_empty(v) for k, v in value.items()
            if not (isinstance(v, (str, list, dict)) and v in _EMPTY)}


def _norm(value):
    """把结构规范成可比的形态：dict 键排序、列表按内容排序（顺序不是语义）。"""
    if isinstance(value, dict):
        return _drop_empty({k: _norm(value[k]) for k in sorted(value)})
    if isinstance(value, (list, tuple)):
        items = [_norm(v) for v in value]
        return sorted(items, key=lambda v: json.dumps(v, ensure_ascii=False, sort_keys=True))
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return value
    return value


def _fingerprint(card) -> dict:
    p = card.profile
    return {
        "prefix": card.prefix,
        "description": card.description,
        # 触发词/声明是「集合」语义：库里按行存，读回来顺序与 YAML 无关
        "keywords": sorted(card.keywords),
        "workflows": [_norm({k: v for k, v in wf.items() if k != "activation_weight"})
                      for wf in card.workflows],
        "chain_refs": _norm(card.chain_refs),
        "plugin_artifacts": _norm(card.plugin_artifacts),
        "readiness": _norm(card.readiness.to_dict() if card.readiness else None),
        "analysis": _norm(p.analysis) if p else None,
        "persona": _norm(p.persona) if p else None,
        "plugin": _norm(p.plugin) if p else None,
        "capability": {
            "core": sorted(p.capability.core) if p else [],
            "tools": sorted(p.capability.tools) if p else [],
            "knowledge": sorted(p.capability.knowledge) if p else [],
            "soft": sorted(p.capability.soft) if p else [],
            "scoring": _norm(p.capability.scoring) if p else {},
        },
        "stakeholders": _norm({
            "upstream": [c.get("value") for c in (card.chain_refs or {}).get("upstream", [])],
            "downstream": [c.get("value") for c in (card.chain_refs or {}).get("downstream", [])],
            "beneficiaries": p.stakeholders.beneficiaries if p else [],
            "blockers": p.stakeholders.blockers if p else [],
            "incentives": p.stakeholders.incentives if p else [],
            "risk_notes": p.stakeholders.risk_notes if p else [],
        }),
    }


def _roundtrip_diff(db_path: str = DB_PATH) -> list:
    """库读回来的卡 vs 内存里的卡，逐字段比。返回差异清单（空=一致）。"""
    cards = dbstore.read(db_path)
    store = RoleCardStore()
    diffs = []
    for card in store.all_cards():
        key = f"{card.unit_id}::{card.role}"
        got = cards.get(key)
        if got is None:
            diffs.append(f"{key}: 库里没有这张卡")
            continue
        want_fp = _fingerprint(card)
        got_fp = _fingerprint(got)
        for field in want_fp:
            if want_fp[field] != got_fp[field]:
                diffs.append(f"{key}.{field}: 库={json.dumps(got_fp[field], ensure_ascii=False)[:120]}"
                             f" 内存={json.dumps(want_fp[field], ensure_ascii=False)[:120]}")
    extra = set(cards) - {f"{c.unit_id}::{c.role}" for c in store.all_cards()}
    diffs += [f"{k}: 库里有、仓库里没有的卡" for k in sorted(extra)]
    return diffs


def main() -> int:
    ap = argparse.ArgumentParser(description="岗位画像 / 行业类 → 真库（SQLite）+ 双方言 DDL")
    ap.add_argument("--check", action="store_true", help="只校验库与数据是否一致（CI 用）")
    ap.add_argument("--stats", action="store_true", help="打印库里有什么")
    ap.add_argument("--query", default="", help="只读查询一条 SQL")
    ap.add_argument("--db", default=DB_PATH, help="库路径（默认 data/db/hanghang.db）")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出（给流水线消费）")
    args = ap.parse_args()

    if args.stats:
        info = dbstore.stats(args.db)
        if args.json:
            print(json.dumps(info, ensure_ascii=False, indent=2))
        else:
            print(f"库: {info['path']}  {info['bytes'] / 1024:.0f} KB  结构版本 {info['version']}")
            print(f"构建: {info['built_at']}  来源 {info['source']}  生成器 {info['generator']}")
            print(f"共 {len(info['tables'])} 张表 / {info['total_rows']} 行")
            for name, rows in info["tables"].items():
                print(f"  {name:<22}{rows:>7}")
        return 0

    if args.query:
        try:
            rows = dbstore.query(args.db, args.query)
        except (FileNotFoundError, PermissionError) as exc:
            print(f"✗ {exc}")
            return 1
        for row in rows:
            print(" | ".join("" if v is None else str(v) for v in row))
        print(f"\n（{len(rows)} 行）")
        return 0

    store = RoleCardStore()
    counts = dbstore.build(store, args.db)
    os.makedirs(os.path.dirname(DDL_SQLITE), exist_ok=True)
    for path, dialect in ((DDL_SQLITE, "sqlite"), (DDL_PG, "postgresql")):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(HEADER + schema_sql.ddl(dialect))

    diffs = _roundtrip_diff(args.db)
    if diffs:
        print(f"✗ 库与数据不一致（{len(diffs)} 处），前 10 条：")
        for d in diffs[:10]:
            print(f"  - {d}")
        return 1

    if args.check:
        print(f"✅ 库与数据一致：{counts['role_profile']} 个岗位 / "
              f"{sum(counts.values())} 行 / 结构 {schema_sql.SCHEMA_VERSION}")
        return 0

    print(f"已重建 {os.path.relpath(args.db, ROOT)}（{os.path.getsize(args.db) / 1024:.0f} KB）")
    for name, rows in counts.items():
        print(f"  {name:<22}{rows:>7}")
    print(f"DDL: {os.path.relpath(DDL_SQLITE, ROOT)} / {os.path.relpath(DDL_PG, ROOT)}")
    print(f"回读校验: ✅ 库读回的 {counts['role_profile']} 张卡与画像逐字段一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
