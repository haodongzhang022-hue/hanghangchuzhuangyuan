#!/usr/bin/env python3
"""行业分区库 → 可导入的建库产物（DDL 进版本库 + 导入往返自检）

回答的是「客户买服务器了，怎么把数据装进去」。分工：

  data/*.yaml               权威源（可评审、可回滚、可被知识库切片）
  data/db/industry/*.sql    结构产物（本脚本生成，进版本库）
  out/industry-db/*         全量导出（`industry export` 生成，含数据 SQL / csv / sqlite）

为什么 DDL 进版本库而数据不进：结构是**契约**，改一列要评审、要能被下游看见；
数据是**可重建**的（yaml 是源），把 1.6 MB 生成 SQL 提交进 git 只会得到看不见的
diff，改一次画像就冲突一次。

用法：
  python3 scripts/export_industry_db.py           # 重生成 data/db/industry/
  python3 scripts/export_industry_db.py --check   # 产物是否过期 + 导入往返是否一致（CI）
  python3 scripts/export_industry_db.py --sqlite out.db   # 真建一份库（给交付用）
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

from hanghang.engine import industry_schema                       # noqa: E402
from hanghang.engine.industry_db import IndustryDatabase           # noqa: E402

OUT_DIR = os.path.join(ROOT, "data", "db", "industry")
HEADER = ("-- ⚠️ 本文件由 scripts/export_industry_db.py 生成，请勿手改。\n"
          "-- 数据（10-data.sql）由 `industry export` 生成，不随结构进版本库。\n")


def _readme() -> str:
    """目录自带说明书：拿到 data/db/industry/ 的人先读到口径，再读表。"""
    lines = ["# 行业分区库 · 结构产物", "",
             "由 `scripts/export_industry_db.py` 生成，请勿手改。",
             "数据 SQL 不在这里（可从 yaml 重建），由 "
             "`industry export --out out/industry-db` 生成 `10-data.sql`。", "",
             "## 导入", "",
             "```bash",
             "# SQLite",
             "sqlite3 hanghang.db < data/db/industry/00-schema.sqlite.sql",
             "sqlite3 hanghang.db < out/industry-db/10-data.sql",
             "# PostgreSQL",
             "psql -d hanghang -f data/db/industry/00-schema.postgresql.sql",
             "psql -d hanghang -f out/industry-db/10-data.sql",
             "```", "",
             "详见 `docs/industry/industry-db-import.md`。", "",
             "## 表", ""]
    for table in industry_schema.TABLES:
        cols = industry_schema.columns_of(table["name"])
        lines.append(f"- `{table['name']}`（{len(cols)} 列）— {table.get('comment', '')}")
    lines += ["", "## 与另一套库的分工", "",
              "`data/db/hanghang.db`（`scripts/build_role_db.py`）装的是岗位画像/工序/就绪度；",
              "本目录装的是职业/分区/归属边/产值口径。两套都「结构单源 + 双方言 + 产物可校验」，",
              "回答的问题不同：一个问「这行业谁付钱、多少钱」，一个问「这岗位怎么干活、还差什么」。",
              ""]
    return "\n".join(lines)


def build() -> dict:
    """要提交的产物：两份方言 DDL + 目录说明。"""
    return {
        "00-schema.sqlite.sql": HEADER + industry_schema.ddl("sqlite"),
        "00-schema.postgresql.sql": HEADER + industry_schema.ddl("postgresql"),
        "README.md": _readme(),
    }


def roundtrip() -> dict:
    """把 schema + 数据真灌进一份临时 SQLite，读回行数。

    这是「能不能导入」的唯一可信验证：只检查文件非空，等于没验 ——
    占位符个数与列数不匹配、字符串转义写错、外键顺序颠倒，文件都照样非空。
    """
    db = IndustryDatabase()
    snapshot = db.compute()
    expect = industry_schema.counts(db, snapshot)
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "industry.db")
        conn = sqlite3.connect(path)
        try:
            conn.executescript(industry_schema.ddl("sqlite"))
            conn.executescript(industry_schema.data_sql(db, snapshot))
            conn.commit()
            got = {}
            for name in industry_schema.tables("sqlite"):
                got[name] = conn.execute(
                    f'SELECT count(*) FROM "{name}"').fetchone()[0]
        finally:
            conn.close()
    return {"expected": expect, "got": got}


def main() -> int:
    ap = argparse.ArgumentParser(description="行业分区库 → 可导入的建库产物")
    ap.add_argument("--check", action="store_true", help="只校验产物是否过期（CI 用）")
    ap.add_argument("--sqlite", default="", help="在指定路径真建一份 SQLite 库（交付用）")
    args = ap.parse_args()

    if args.sqlite:
        db = IndustryDatabase()
        snapshot = db.compute()
        path = os.path.abspath(args.sqlite)
        if os.path.exists(path):
            os.remove(path)
        conn = sqlite3.connect(path)
        try:
            conn.executescript(industry_schema.ddl("sqlite"))
            conn.executescript(industry_schema.data_sql(db, snapshot))
            conn.commit()
        finally:
            conn.close()
        print(f"已建库 {path}（{os.path.getsize(path) / 1024:.0f} KB）")
        for name, n in industry_schema.counts(db, snapshot).items():
            print(f"  {name:<16}{n:>7}")
        return 0

    files = build()
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

    rt = roundtrip()
    bad = {k: (rt["expected"][k], rt["got"].get(k)) for k in rt["expected"]
           if rt["expected"][k] != rt["got"].get(k)}

    if args.check:
        if stale:
            print(f"✗ 结构产物已过期：{', '.join(stale)}")
            print("  跑 python3 scripts/export_industry_db.py 重生成后提交。")
            return 1
        if bad:
            print(f"✗ 导入往返行数不一致：{bad}")
            return 1
        total = sum(rt["got"].values())
        print(f"✅ 行业分区库结构产物与数据一致，导入往返 {len(rt['got'])} 表 / {total} 行")
        return 0

    print(f"已生成 {len(files)} 个文件 → data/db/industry/（变更 {len(stale)} 个）")
    if bad:
        print(f"✗ 导入往返行数不一致：{bad}")
        return 1
    print(f"导入往返自检: ✅ {sum(rt['got'].values())} 行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
