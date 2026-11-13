#!/usr/bin/env python3
"""把行业类词表导出成「数据库形态」：DDL + 数据 + 数据字典。

一个 YAML 装全部类目，查不了、join 不了、也没法分工维护；真正能管住它的是
**结构**：类目表 / 别名表 / 索引源表 / 岗位引用表。这个脚本产出那套结构，
但不连接任何数据库、不落凭据、不落公司名录。

用法：
  python3 scripts/export_class_db.py                 # 写 data/db/*.sql 与数据字典
  python3 scripts/export_class_db.py --check         # 只校验是否已过期（CI 用）
  python3 scripts/export_class_db.py --stdout ddl    # 打到标准输出（ddl|data|dict）

注意：这里产的是**结构文本**；真正能开的库由 scripts/build_role_db.py 建。
两者分工：这里回答「类目长什么样」，那边回答「数据怎么存、怎么 join」。
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../src"))

from hanghang.rolecard import RoleCardStore              # noqa: E402
from hanghang.rolecard import schema_sql                # noqa: E402

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
OUT_DIR = os.path.join(REPO_ROOT, "data", "db")
HEADER = "-- ⚠️ 本文件由 scripts/export_class_db.py 生成，请勿手改。\n"


def build():
    store = RoleCardStore()
    usage = store.class_usage()
    return {
        # 旧的类目专用结构文本：完整库结构已由 build_role_db.py 双方言产出，
        # 这里只保留「类目四表」那份口径快照，避免两处各写一套完整 DDL。
        "00-class-tables.sql": HEADER + schema_sql.class_table_ddl(),
        "10-classes.sql": HEADER + schema_sql.data_sql(store.classes, usage),
        "README.md": schema_sql.dictionary_md(store.classes, usage),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="行业类词表 → 数据库结构")
    ap.add_argument("--check", action="store_true", help="只校验产物是否与数据一致")
    ap.add_argument("--stdout", choices=["ddl", "data", "dict"], help="打到标准输出")
    args = ap.parse_args()

    files = build()
    if args.stdout:
        key = {"ddl": "00-schema.sql", "data": "10-classes.sql", "dict": "README.md"}[args.stdout]
        sys.stdout.write(files[key])
        return 0

    stale = []
    for name, content in files.items():
        path = os.path.join(OUT_DIR, name)
        old = None
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                old = fh.read()
        if old != content:
            stale.append(name)
            if not args.check:
                os.makedirs(OUT_DIR, exist_ok=True)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(content)

    if args.check:
        if stale:
            print(f"✗ 数据字典/DDL 已过期：{', '.join(stale)}")
            print("  跑 python3 scripts/export_class_db.py 重生成后提交。")
            return 1
        print("✅ 行业类数据库产物与词表一致")
        return 0

    print(f"已生成 {len(files)} 个文件 → data/db/（变更 {len(stale)} 个）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
