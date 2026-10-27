"""M11 行业分区定义库测试

核心断言（对应用户要求）：
1. 职业是解耦最小单位：职业 id 稳定、可跨分区复用、不受行业命名影响。
2. 行业是聚类结果：分区成员由 occupation.unit_id 反查得到，不手写第二份清单。
3. 双向对齐：注册单元每个岗位都有职业登记；职业挂的分区必须真实存在且岗位匹配。
4. 产值口径诚实：无市场口径的分区必须留 null，不得填 0 假装有数据。
5. 导出可用：csv/json/sqlite 三种扁平表可为制品库/知识库直接消费。
"""
import os
import sys
import json
import sqlite3
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from hanghang.engine.industry_db import IndustryDatabase


def test_partition_and_occupation_loaded():
    db = IndustryDatabase()
    assert len(db.partitions) >= 30
    assert len(db.occupations) >= 100
    ids = [o["id"] for o in db.occupations]
    assert len(ids) == len(set(ids)), "职业 id 必须唯一（稳定主键）"


def test_members_are_derived_not_duplicated():
    """分区成员 = 反查 occupation.unit_id，数据里不重复存职业清单"""
    db = IndustryDatabase()
    p = db.partition("dongjiagoushi")
    assert p is not None
    members = db.members_of("dongjiagoushi")
    assert {o["unit_role"] for o in members} == {
        "secretary", "architect", "developer", "reviewer", "product"}
    # 分区定义本身不含 members 字段，避免两份清单分叉
    assert "members" not in p


def test_bidirectional_alignment():
    """职业↔单元岗位 双向对齐，无纸面覆盖"""
    db = IndustryDatabase()
    assert db.validate() == []


def test_coverage_ratio_consistent():
    db = IndustryDatabase()
    s = db.compute()
    assert 0 < s["partition_coverage"] < 1
    assert s["covered_partitions"] == 14
    assert s["buildable_partitions"] == s["covered_partitions"] + len(db.gaps())
    assert 0 < s["occupation_coverage"] < 1


def test_gdp_null_is_not_zero():
    """无市场口径的分区必须留 null，不得用 0 冒充数据"""
    db = IndustryDatabase()
    for pid in ("admin-office", "public-affairs"):
        p = db.partition(pid)
        assert p["gdp_cny"] is None, f"{pid} 不应编造产值"
        assert "不适用" in p["gdp_source"]
    # 有产值口径的分区必须给出 scope 与 source
    for p in db.partitions:
        if p.get("gdp_cny"):
            assert p.get("gdp_scope") and p.get("gdp_source"), p["id"]


def test_provider_mix_present():
    """每个分区的供给结构(ai/hybrid/human)自洽"""
    db = IndustryDatabase()
    for p in db.partitions:
        mix = p["provider_mix"]
        assert set(mix) == {"ai", "hybrid", "human"}
        assert sum(mix.values()) == 100


def test_occupation_decoupled_from_naming():
    """同一职业可按不同单元角色复用；name 可改而 id 稳定"""
    db = IndustryDatabase()
    o = db.occupation("translator")
    assert o is not None
    assert not o.get("unit_id")  # 翻译分区尚未建单元，但职业已登记，不丢
    # 未挂分区职业可被列出（缺漏可视）
    unassigned = {x["id"] for x in db.unassigned_occupations()}
    assert "translator" in unassigned
    assert "qa-engineer" in unassigned


def test_provider_filter():
    db = IndustryDatabase()
    ai = db.by_provider("ai")
    assert ai, "应存在高 AI 替代度职业"
    assert all(o["provider"] == "ai" for o in ai)
    assert db.by_billing("usage"), "应存在按次收费职业"


def test_export_flat_tables():
    db = IndustryDatabase()
    with tempfile.TemporaryDirectory() as td:
        from hanghang.cli.industry_commands import cmd_industry_export

        class A:
            out = td
            format = "all"
            data_dir = ""

        cmd_industry_export(A)
        for f in ("industry-db.json", "partitions.csv", "occupations.csv",
                  "industry.sqlite"):
            assert os.path.exists(os.path.join(td, f)), f

        with open(os.path.join(td, "industry-db.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        assert len(data["partitions"]) == len(db.partitions)

        conn = sqlite3.connect(os.path.join(td, "industry.sqlite"))
        n_part = conn.execute("select count(*) from partition").fetchone()[0]
        n_occ = conn.execute("select count(*) from occupation").fetchone()[0]
        # sqlite 可直接按分区聚合成员数
        row = conn.execute(
            "select count(*) from occupation where partition_id='dongjiagoushi'"
        ).fetchone()[0]
        conn.close()
        assert n_part == len(db.partitions)
        assert n_occ == len(db.occupations)
        assert row == 5


if __name__ == "__main__":
    test_partition_and_occupation_loaded()
    test_members_are_derived_not_duplicated()
    test_bidirectional_alignment()
    test_coverage_ratio_consistent()
    test_gdp_null_is_not_zero()
    test_provider_mix_present()
    test_occupation_decoupled_from_naming()
    test_provider_filter()
    test_export_flat_tables()
    print("✅ 行业分区定义库测试通过")
