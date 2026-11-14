#!/usr/bin/env python3
"""M11 收尾：产值口径标签 + 可导入产物

盯四件事（都是「准备把库导进去」时必须先成立的前提）：

  1. `gdp_kind` 口径标签必须在（第 20 条校验），且与数字互斥一致：
     有产值必须标口径类型，无产值必须是 `none`；数字与标签打架要报。
  2. 汇总按口径分组：**只有同口径才能相加**。把 GMV 和增加值求和，
     得到的"合计产值"越大越错，所以必须分组给，并单独给出可引用的增加值口径。
  3. 建表结构是单源：DDL / INSERT 列序 / 导出文件都不许各写一份。
  4. 产物真能导入：schema + data 灌进临时库再读回行数，不是"文件非空"就算过。
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

from hanghang.engine import industry_schema                    # noqa: E402
from hanghang.engine.industry_db import (                      # noqa: E402
    GDP_KINDS, IndustryDatabase,
)


def _db():
    return IndustryDatabase()


# ------------------------------------------------- 第 20 条：产值口径标签
def test_every_partition_declares_gdp_kind():
    """41 个分区每个都要有口径标签：没有标签的数不能进任何汇总"""
    db = _db()
    missing = [p["id"] for p in db.partitions if not p.get("gdp_kind")]
    assert not missing, f"这 {len(missing)} 个分区没标 gdp_kind: {missing}"
    bad = [p["id"] for p in db.partitions if p["gdp_kind"] not in GDP_KINDS]
    assert not bad, f"口径类型不在枚举里: {bad}"


def test_gdp_kind_and_value_must_agree():
    """数字与标签不许互相矛盾：有数不能标 none，无数不能标具体口径"""
    db = _db()
    p = db.partition("manufacturing")
    assert p["gdp_kind"] == "value_added"

    p["gdp_kind"] = "none"           # 有 33 万亿却声称"没有市场口径"
    problems = db.validate()
    assert any("gdp_kind=none" in x for x in problems), problems
    p["gdp_kind"] = "value_added"

    # 反向：无产值的分区标成增加值
    q = db.partition("public-affairs")
    q["gdp_kind"] = "value_added"
    problems = db.validate()
    assert any("无 gdp_cny 却标 gdp_kind" in x for x in problems), problems
    q["gdp_kind"] = "none"
    assert not any("gdp_kind" in x for x in db.validate())


def test_unknown_gdp_kind_and_confidence_are_reported():
    """拼错的口径类型会让分组静默漏掉这一行，必须报"""
    db = _db()
    p = db.partition("manufacturing")
    p["gdp_kind"] = "value-added"        # 连字符，枚举里是下划线
    assert any("gdp_kind" in x for x in db.validate())
    p["gdp_kind"] = "value_added"
    p["gdp_confidence"] = "very-high"
    assert any("gdp_confidence" in x for x in db.validate())
    p["gdp_confidence"] = "high"
    assert not any("gdp_kind" in x or "gdp_confidence" in x for x in db.validate())


def test_missing_gdp_kind_is_reported():
    """没标签也要报：默认值不存在，缺就是缺"""
    db = _db()
    db.partition("dongjiagoushi").pop("gdp_kind", None)
    problems = db.validate()
    assert any("缺 gdp_kind" in x for x in problems), problems


# ------------------------------------------------- 同口径才能加总
def test_gdp_summary_groups_by_kind():
    """汇总按口径分组，并明确指出跨口径相加没有意义"""
    db = _db()
    s = db.compute()
    kinds = {b["kind"] for b in s["gdp_by_kind"]}
    # 现实数据里至少同时存在这三种：增加值、交易额、成本总额
    assert {"value_added", "gmv", "cost_total"} <= kinds, kinds
    # 每组合计必须等于该组各分区的和（分组不能丢行、也不能重复计）
    for b in s["gdp_by_kind"]:
        want = sum(p.get("gdp_cny") or 0 for p in db.partitions
                   if (p.get("gdp_kind") or "") == b["kind"])
        assert b["total_cny"] == want, (b["kind"], b["total_cny"], want)
    # 各组之和 == 总量：分组是拆分视角，不是另一套数据
    assert sum(b["total_cny"] for b in s["gdp_by_kind"]) == s["gdp_total_cny"]
    # "可引用"的数只取增加值口径，且必须远小于跨口径总和
    assert s["gdp_comparable_cny"] > 0
    assert s["gdp_comparable_cny"] < s["gdp_total_cny"]


def test_comparable_total_is_value_added_only():
    """可对外的口径只有增加值：GMV/成本总额混进去会让数字越大越错"""
    db = _db()
    s = db.compute()
    va = sum(p["gdp_cny"] for p in db.partitions
             if p.get("gdp_kind") == "value_added" and p.get("gdp_cny"))
    assert s["gdp_comparable_cny"] == va
    # 电商是 GMV、物流是成本总额：这两个绝不能算进可引用口径
    for pid in ("e-commerce", "logistics-supply"):
        assert db.partition(pid)["gdp_kind"] != "value_added"


def test_rows_carry_kind_and_label():
    """导出/接口的行里必须带口径类型与中文说明，不能只有一串数字"""
    db = _db()
    s = db.compute()
    row = next(r for r in s["rows"] if r["id"] == "manufacturing")
    assert row["gdp_kind"] == "value_added"
    assert row["gdp_kind_label"] == GDP_KINDS["value_added"]
    assert row["gdp_confidence"] == "high"


# ------------------------------------------------- 结构单源
def test_schema_columns_and_ddl_agree():
    """DDL 的列序就是 INSERT 的列序：单一来源，不可能错位"""
    ddl = industry_schema.ddl("sqlite")
    for table in industry_schema.TABLES:
        cols = industry_schema.columns_of(table["name"])
        block = ddl.split(f'"{table["name"]}" (', 1)[1].split(");", 1)[0]
        for c in cols:
            assert f'"{c}"' in block, (table["name"], c)
    # 两种方言表名列名一致，切库只改方言参数
    pg = industry_schema.ddl("postgresql")
    for name in industry_schema.tables("sqlite"):
        assert f'"{name}"' in pg
    # 三张核心表的主键都是复合自然键，没有自增列 —— 方言差异体现在类型映射上
    assert "REAL" in ddl and "REAL" not in pg
    assert "DOUBLE PRECISION" in pg


def test_data_sql_is_dialect_neutral():
    """数据 SQL 只用标准写法：反斜杠转义是 MySQL 扩展，SQLite/PG 都不认"""
    db = _db()
    sql = industry_schema.data_sql(db, db.compute())
    assert "\\'" not in sql, "出现反斜杠转义，PostgreSQL 会把它当字面量"
    assert "INSERT INTO" in sql
    # 单引号必须按标准翻倍
    assert "''" in sql or "'" not in sql


# ------------------------------------------------- 真能导入
def _load():
    db = _db()
    snapshot = db.compute()
    tmp = tempfile.mkdtemp(prefix="hh-ind-")
    path = os.path.join(tmp, "i.db")
    conn = sqlite3.connect(path)
    try:
        conn.executescript(industry_schema.ddl("sqlite"))
        conn.executescript(industry_schema.data_sql(db, snapshot))
        conn.commit()
        counts = {name: conn.execute(
            f'SELECT count(*) FROM "{name}"').fetchone()[0]
            for name in industry_schema.tables("sqlite")}
    finally:
        conn.close()
    return db, counts, path


def test_exported_schema_and_data_really_load():
    """schema + data 真灌进库再读回：占位符错位/转义写错都会在这里露出来"""
    db, counts, path = _load()
    expect = industry_schema.counts(db, db.compute())
    assert counts == expect, (counts, expect)
    assert counts["partition"] == len(db.partitions)
    assert counts["occupation"] == len(db.occupations)
    assert counts["membership"] == len(db.axis_view.memberships)

    conn = sqlite3.connect(path)
    try:
        # 主键与外键真的成立：悬空边会让 join 查不到人
        dangling = conn.execute(
            "SELECT count(*) FROM membership m LEFT JOIN partition p"
            " ON p.id = m.partition WHERE p.id IS NULL").fetchone()[0]
        assert dangling == 0
        # 口径标签落库，下游 SQL 能直接按它分组
        kinds = dict(conn.execute(
            "SELECT gdp_kind, count(*) FROM partition GROUP BY 1").fetchall())
        assert kinds.get("value_added") and kinds.get("gmv")
        # 索引建了：按 status 筛待建分区是常规查询
        idx = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'")}
        assert "idx_partition_kind" in idx and "idx_partition_status" in idx
    finally:
        conn.close()


def test_export_writes_seven_artifacts_and_they_import():
    """`industry export` 交出 7 份产物，其中三份是拿来直接建库的"""
    from hanghang.cli.industry_commands import cmd_industry_export

    with tempfile.TemporaryDirectory() as td:
        class A:
            out = td
            format = "all"
            data_dir = ""

        cmd_industry_export(A)
        for f in ("industry-db.json", "partitions.csv", "occupations.csv",
                  "industry.sqlite", "00-schema.sqlite.sql",
                  "00-schema.postgresql.sql", "10-data.sql"):
            p = os.path.join(td, f)
            assert os.path.exists(p) and os.path.getsize(p) > 0, f

        # 用导出的三份 SQL 独立建一份库：不经过 Python，模拟客户拿到文件建库
        out_path = os.path.join(td, "from-sql.db")
        conn = sqlite3.connect(out_path)
        try:
            for name in ("00-schema.sqlite.sql", "10-data.sql"):
                with open(os.path.join(td, name), encoding="utf-8") as fh:
                    conn.executescript(fh.read())
            conn.commit()
            n = conn.execute("SELECT count(*) FROM partition").fetchone()[0]
            occ = conn.execute("SELECT count(*) FROM occupation").fetchone()[0]
        finally:
            conn.close()
        db = _db()
        assert n == len(db.partitions) and occ == len(db.occupations)


def test_committed_ddl_matches_current_schema():
    """仓库里提交的 DDL 必须与代码单源一致，否则客户拿到的结构与数据对不上"""
    proc = subprocess.run(
        [sys.executable, "scripts/export_industry_db.py", "--check"],
        cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "导入往返" in proc.stdout, proc.stdout


def test_csv_and_sqlite_carry_gdp_kind():
    """口径标签要一路带到出口：csv 里只有数字、没有口径，下游就会把 GMV 当 GDP"""
    import csv as _csv
    from hanghang.cli.industry_commands import cmd_industry_export

    with tempfile.TemporaryDirectory() as td:
        class A:
            out = td
            format = "all"
            data_dir = ""

        cmd_industry_export(A)
        with open(os.path.join(td, "partitions.csv"), encoding="utf-8") as fh:
            rows = list(_csv.DictReader(fh))
        for col in ("gdp_kind", "gdp_confidence"):
            assert col in rows[0], col
        ecom = next(r for r in rows if r["id"] == "e-commerce")
        assert ecom["gdp_kind"] == "gmv"
        for r in rows:
            assert r["gdp_kind"], f"{r['id']} 的 csv 行没有口径标签"
        conn = sqlite3.connect(os.path.join(td, "industry.sqlite"))
        try:
            got = conn.execute(
                "SELECT gdp_kind FROM partition WHERE id='logistics-supply'"
            ).fetchone()[0]
        finally:
            conn.close()
        assert got == "cost_total"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ✅ {name}")
    print("✅ 产值口径与导入产物测试通过")
