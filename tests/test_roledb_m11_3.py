#!/usr/bin/env python3
"""M11.3 实库回归：库要能建、能开、能查、能回读，且不藏公司名录。

盯五件事（都是「DDL 不是库」之后必须成立的前提）：
  1. 库真的建出来了，表结构与单源定义一致（不是一份手抄的 SQL）
  2. 库读回来的岗位卡与内存画像逐字段相同（否则库会静默和仓库分叉）
  3. 列表型字段一条一行，能按值查、能 join、能统计（不是 JSON 塞一列）
  4. 仍然没有公司名录表，也没有公司形态的值
  5. 换服务器只改方言：PostgreSQL DDL 与 SQLite 同表同列
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

from hanghang.rolecard import RoleCardStore, dbstore, schema_sql   # noqa: E402


def _built() -> str:
    """在临时目录建一份库（不污染工作区，也不依赖已提交的产物）。"""
    tmp = tempfile.mkdtemp(prefix="hh-db-")
    path = os.path.join(tmp, "t.db")
    dbstore.build(RoleCardStore(), path, when="2026-01-01T00:00:00Z")
    return path


def test_db_builds_all_tables():
    path = _built()
    assert os.path.getsize(path) > 100 * 1024, "库太小，疑似没落数据"
    conn = sqlite3.connect(path)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    for name in schema_sql.tables("sqlite"):
        assert name in tables, f"缺表 {name}"
    assert conn.execute("SELECT count(*) FROM industry_class").fetchone()[0] > 50
    # 画像行数必须与注册岗位数对齐：写死数字会让"新增岗位"变成一次无意义的改测试，
    # 而真正该守的是「注册表里的岗位，一个都不能在库里缺画像」。
    want = {f"{u.unit_id}::{r.name}" for u in RoleCardStore().registry.all_units()
            for r in u.roles}
    got = {f"{u}::{r}" for u, r in conn.execute(
        "SELECT unit_id, role_name FROM role_profile")}
    assert got == want, f"库里画像与注册岗位不一致：缺 {sorted(want - got)} 多 {sorted(got - want)}"
    conn.close()


def test_role_without_profile_roundtrips_as_none():
    """没写画像的岗位（注册表有、画像还没写）读回来必须是 profile=None。

    写成一行全空的 role_profile 会让 read() 造出一份空壳 RoleProfile：
    「还没写画像」被读成「画像写了但六维全空」，--check 与调用方都被骗。
    新岗位一律先接路由、画像后补，这类岗位一定会出现，所以不能靠"当前数据恰好没有"来守。

    做法：把一张真实的卡置成 profile=None，单独建一份库来验——不依赖现有画像的完整度。
    """
    store = RoleCardStore()
    cards = store.all_cards()
    assert cards, "注册表为空，无法验证"
    cards[0].profile = None
    cards[0].plugin_artifacts = []

    class _Stub:
        registry = store.registry
        classes = store.classes
        profiles = store.profiles
        def all_cards(self_inner):
            return cards

    tmp = tempfile.mkdtemp(prefix="hh-db-noprof-")
    path = os.path.join(tmp, "t.db")
    dbstore.build(_Stub(), path, when="2026-01-01T00:00:00Z")
    back = dbstore.read(path)[f"{cards[0].unit_id}::{cards[0].role}"]
    assert back.profile is None, f"无画像岗位读回来变成了 {back.profile!r}"

    conn = sqlite3.connect(path)
    n = conn.execute("SELECT count(*) FROM role_profile WHERE unit_id=? AND role_name=?",
                     (cards[0].unit_id, cards[0].role)).fetchone()[0]
    conn.close()
    assert n == 0, "无画像的岗位不该落 role_profile 行（缺行才是准确表达）"


def test_db_schema_single_source_matches_ddl():
    """库里的列与 DDL 单源定义一致：改表只改一处，库和 DDL 不会各说各话。"""
    path = _built()
    conn = sqlite3.connect(path)
    for table in schema_sql._TABLES:                      # noqa: SLF001 同包单源
        cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{table["name"]}")')]
        want = [c[0] for c in table["columns"]]
        assert cols == want, f"{table['name']} 列不一致: {cols} != {want}"
    conn.close()


def test_db_roundtrip_matches_profiles():
    """库读回来的卡 == 内存里的卡：库不会静默落后于仓库里的画像。"""
    path = _built()
    cards = dbstore.read(path)
    store = RoleCardStore()
    for card in store.all_cards():
        got = cards.get(f"{card.unit_id}::{card.role}")
        assert got is not None, f"{card.unit_id}/{card.role} 库里有缺"
        assert got.prefix == card.prefix
        assert got.profile.analysis["mission"] == card.profile.analysis.get("mission")
        assert got.capability().scoring == card.capability().scoring
        assert [s.id for s in got.playbook()] == [s.id for s in card.playbook()], card.role
        assert got.readiness.score == card.readiness.score, card.role
        assert [c["value"] for c in got.chain_refs.get("upstream", [])] == \
            [c["value"] for c in card.chain_refs.get("upstream", [])], card.role


def test_db_list_fields_are_rows_not_json():
    """交付物/KPI/上下游一条一行：能按值查、能 join，不是 JSON 塞一列。"""
    path = _built()
    conn = sqlite3.connect(path)
    rows = conn.execute(
        "SELECT DISTINCT field FROM role_profile_item ORDER BY field").fetchall()
    fields = {r[0] for r in rows}
    assert {"deliverables", "kpis", "constraints", "core"} <= fields, fields
    # 同一个值在多处出现时能被检出（JSON 列做不到）
    top = conn.execute(
        "SELECT value, count(*) c FROM role_profile_item GROUP BY value"
        " HAVING c > 3 ORDER BY c DESC LIMIT 1").fetchone()
    assert top and top[1] > 3, top
    # 岗位 × 类目的引用能 join 回类目表
    joined = conn.execute(
        "SELECT count(*) FROM role_chain_ref r JOIN industry_class c ON c.name = r.class_name")
    assert joined.fetchone()[0] > 200
    conn.close()


def test_db_chain_refs_keep_role_and_interface_kinds():
    """链条上「岗位/接口」两类落点也要进库，不能只存类目。"""
    path = _built()
    conn = sqlite3.connect(path)
    kinds = {r[0] for r in conn.execute(
        "SELECT DISTINCT ref_kind FROM role_chain_ref")}
    assert {"industry_class", "role"} <= kinds, kinds
    got = conn.execute(
        "SELECT ref_unit FROM role_chain_ref WHERE ref_kind='role' LIMIT 1").fetchone()
    assert got and got[0], "role 类落点应带出所属单元"
    conn.close()


def test_db_has_no_company_table_or_values():
    path = _built()
    conn = sqlite3.connect(path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert not any(x in t for t in tables for x in ("company", "enterprise", "vendor")), tables
    dump = "\n".join(conn.iterdump())
    for marker in ("有限公司", "有限责任公司", "某某厂"):
        assert marker not in dump, f"公司形态的值进了库：{marker}"
    conn.close()


def test_db_query_is_readonly():
    path = _built()
    rows = dbstore.query(path, "SELECT count(*) FROM industry_class")
    assert rows[0][0] > 50
    try:
        dbstore.query(path, "DELETE FROM industry_class")
    except PermissionError:
        pass
    else:
        raise AssertionError("写语句必须被拒绝")


def test_db_dialects_share_tables_and_columns():
    """换服务器只改方言：两种 DDL 表名列名一致。"""
    sq = schema_sql.ddl("sqlite")
    pg = schema_sql.ddl("postgresql")
    for name in schema_sql.tables("sqlite"):
        assert f'"{name}"' in sq and f'"{name}"' in pg, name
    assert "AUTOINCREMENT" in sq and "AUTOINCREMENT" not in pg
    assert "IDENTITY" in pg
    # PG 方言在建表语句层面可解析（不做真连库：无服务、无凭据）
    assert pg.count("CREATE TABLE IF NOT EXISTS") == len(schema_sql._TABLES)  # noqa: SLF001


def test_script_check_and_stats():
    """脚本也要能在无库的干净树上跑：库路径显式指到临时目录。"""
    path = _built()
    proc = subprocess.run([sys.executable, "scripts/build_role_db.py", "--check", "--db", path],
                          cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "库与数据一致" in proc.stdout, proc.stdout

    proc = subprocess.run([sys.executable, "scripts/build_role_db.py", "--stats", "--db", path],
                          cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "张表" in proc.stdout and "role_profile" in proc.stdout, proc.stdout


def test_cli_role_db():
    """CLI 读库要能在干净检出上跑：库由用例现建，不假定 data/db/hanghang.db 已在。"""
    path = _built()
    proc = subprocess.run([sys.executable, "src/hanghang/cli/main.py", "role", "db",
                           "--db", path,
                           "--sql", "SELECT count(*) AS n FROM industry_class"],
                          cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "（1 行）" in proc.stdout, proc.stdout


def test_no_test_depends_on_gitignored_db():
    """病根护栏：任何用例都不许假定 data/db/hanghang.db 已经在。

    data/db/*.db 不入库，干净检出后文件本就不存在。把默认库临时挪走再跑
    一轮本文件，必须仍全通过，且不许把默认库顺手建回来——否则「冷启动必红」
    只是被前一个用例的副作用掩盖。
    """
    if os.environ.get("HH_SKIP_DB_GUARD"):
        return  # 递归调用里不再嵌套
    default_db = os.path.join(ROOT, dbstore.DEFAULT_DB_PATH)
    hidden = default_db + ".hidden"
    moved = os.path.exists(default_db)
    if moved:
        os.replace(default_db, hidden)
    try:
        proc = subprocess.run([sys.executable, os.path.abspath(__file__)],
                              cwd=ROOT, capture_output=True, text=True,
                              env={**os.environ, "HH_SKIP_DB_GUARD": "1"})
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert not os.path.exists(default_db), "用例在默认路径上建了库，冷启动仍会被掩盖"
    finally:
        if moved:
            os.replace(hidden, default_db)


def test_cli_role_db_missing_reports_how_to_build():
    """缺库得说人话，不能抛 traceback 也不能静默当空库。"""
    tmp = tempfile.mkdtemp(prefix="hh-nodb-")
    path = os.path.join(tmp, "absent.db")
    proc = subprocess.run([sys.executable, "src/hanghang/cli/main.py", "role", "db",
                           "--db", path, "--sql", "SELECT 1"],
                          cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode != 0, proc.stdout
    assert "库不存在" in proc.stdout and "build_role_db" in proc.stdout, proc.stdout
    assert "Traceback" not in proc.stdout + proc.stderr, proc.stderr


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✅ {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  ❌ {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  ❌ {t.__name__}: {type(e).__name__}: {e}")
    print("✅ M11.3 实库测试全部通过" if not failed else f"❌ {failed} 个测试失败")
    raise SystemExit(1 if failed else 0)
