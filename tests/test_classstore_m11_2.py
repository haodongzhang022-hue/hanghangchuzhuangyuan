#!/usr/bin/env python3
"""M11.2 词表目录化 + 数据库形态 + 云仓检索 的回归断言。

盯三件事（都是「一个 YAML 装不下」之后必须成立的前提）：
  1. 目录化拼装的结果与拆分前等价，且每个类目能溯源到具体文件
  2. DDL/数据字典可执行、可 join，且**不含公司名录**
  3. 云仓不可用时降级为本地检索，而不是把主流程搞挂
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

from hanghang.rolecard import RoleCardStore, cloudstore          # noqa: E402
from hanghang.rolecard.yamlload import load, load_dir           # noqa: E402


def _store() -> RoleCardStore:
    return RoleCardStore()


def test_class_dir_splits_by_domain():
    """词表按域拆成多个文件，不是一个大 YAML。"""
    store = _store()
    files = sorted(f for f in os.listdir(os.path.join(ROOT, "data", "industry-classes"))
                   if f.endswith(".yaml"))
    assert len(files) >= 5, f"域文件太少：{files}"
    assert store.classes.sources, "类目缺少来源溯源"
    assert len({store.classes.sources[n] for n in store.classes.classes}) > 1, \
        "所有类目都来自同一个文件，目录化没生效"


def test_class_dir_matches_summary_entry():
    """汇总入口用 !include 拼装，内容与逐文件读取一致。"""
    store = _store()
    merged = load_dir(os.path.join(ROOT, "data", "industry-classes"))
    summary = load(os.path.join(ROOT, "data", "industry-classes.yaml"))
    assert sorted(summary["classes"]) == sorted(store.classes.classes), "汇总与加载结果不一致"
    assert sorted(merged["classes"]) == sorted(store.classes.classes), "目录直读与加载结果不一致"


def test_include_handles_same_leaf_key():
    """!include 各文件都用同一个顶层 key，不能因为覆盖只剩最后一个文件。"""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        for name, body in (("a.yaml", "classes:\n  aaa: {kind: X}\n"),
                           ("b.yaml", "classes:\n  bbb: {kind: Y}\n")):
            with open(os.path.join(tmp, name), "w", encoding="utf-8") as fh:
                fh.write(body)
        with open(os.path.join(tmp, "all.yaml"), "w", encoding="utf-8") as fh:
            fh.write("classes: !include [a.yaml, b.yaml]\n")
        data = load(os.path.join(tmp, "all.yaml"))
        assert sorted(data["classes"]) == ["aaa", "bbb"], data


def test_include_rejects_missing_and_cycle():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "loop.yaml"), "w", encoding="utf-8") as fh:
            fh.write("classes: !include loop.yaml\n")
        try:
            load(os.path.join(tmp, "loop.yaml"))
        except Exception as exc:                      # noqa: BLE001 任意失败都算拦住
            assert "循环" in str(exc), exc
        else:
            raise AssertionError("循环 include 应当报错")


def test_db_ddl_executes_and_joins():
    """DDL + 数据能在 SQLite 里跑通，且四张表互相能 join。"""
    store = _store()
    from hanghang.rolecard import schema_sql
    conn = sqlite3.connect(":memory:")
    conn.executescript(schema_sql.DDL)
    conn.executescript(schema_sql.data_sql(store.classes, store.class_usage()))

    total = conn.execute("SELECT count(*) FROM industry_class").fetchone()[0]
    assert total == len(store.classes.classes), (total, len(store.classes.classes))

    rows = conn.execute("""
        SELECT c.name, s.source FROM industry_class c
        JOIN class_index_src s ON s.class_name = c.name
        WHERE c.name = '钢材加工'
    """).fetchall()
    assert rows and rows[0][1] == "企业名录", rows

    refs = conn.execute("""
        SELECT count(*) FROM role_chain_ref r
        JOIN industry_class c ON c.name = r.class_name
    """).fetchone()[0]
    assert refs > 0, "岗位引用没有落进表"


def test_db_has_no_company_table():
    """公司名录不该有表：仓库只存检索方式。"""
    store = _store()
    from hanghang.rolecard import schema_sql
    conn = sqlite3.connect(":memory:")
    conn.executescript(schema_sql.DDL)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "industry_class" in tables
    assert not any("company" in t or "enterprise" in t or "vendor" in t for t in tables), tables

    conn.executescript(schema_sql.data_sql(store.classes, store.class_usage()))
    dumped = "\n".join(conn.iterdump())
    assert "有限公司" not in dumped, "公司形态的值被写进了数据库"


def test_export_script_check_passes():
    proc = subprocess.run([sys.executable, "scripts/export_class_db.py", "--check"],
                          cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_cloudstore_degrades_without_token():
    """没有 token 时抛 CloudUnavailable，由调用方降级，不静默返回空。"""
    store = _store()
    old = os.environ.pop("CNB_TOKEN", None)
    try:
        try:
            cloudstore.query("钢材加工")
        except cloudstore.CloudUnavailable as exc:
            assert "CNB_TOKEN" in str(exc), exc
        else:
            raise AssertionError("无 token 时应抛 CloudUnavailable")

        result = cloudstore.locate_class("钢材加工的上游", store.classes)
        assert "钢材加工" in result["classes"], result
        assert result["source"] == "local", result
        assert result.get("note"), "应说明为什么走了本地"
    finally:
        if old is not None:
            os.environ["CNB_TOKEN"] = old


def test_cloudstore_local_skips_noise():
    """本地兜底不把「单元」「岗位类」这类满地都是的词当命中。"""
    store = _store()
    result = cloudstore.locate_class("帮我做个软件研发的架构方案", store.classes)
    assert "dongjiagoushi" not in result["classes"], result


def test_cli_role_classes_reports_files():
    proc = subprocess.run([sys.executable, "src/hanghang/cli/main.py", "role", "classes"],
                          cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "industry-classes/" in proc.stdout, proc.stdout
    assert "个文件" in proc.stdout, proc.stdout


def test_cli_role_search_local_only():
    env = dict(os.environ)
    env.pop("CNB_TOKEN", None)
    proc = subprocess.run([sys.executable, "src/hanghang/cli/main.py", "role",
                           "search", "钢材加工的上游"],
                          cwd=ROOT, capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "钢材加工" in proc.stdout, proc.stdout
    assert "本地" in proc.stdout or "local" in proc.stdout, proc.stdout


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"  ❌ {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  ❌ {t.__name__}: {type(e).__name__}: {e}")
    print("✅ M11.2 词表目录化 / 数据库 / 云仓 测试全部通过" if not failed
          else f"❌ {failed} 个测试失败")
    raise SystemExit(1 if failed else 0)
