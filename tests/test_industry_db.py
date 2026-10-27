"""M11 行业分区定义库测试

核心断言（对应用户要求）：
1. 职业是解耦最小单位：职业 id 稳定、单值 unit_id 挂唯一分区（多归属暂不支持）、
   不受行业命名影响。
2. 行业是聚类结果：分区成员由 occupation.unit_id 反查得到，不手写第二份清单。
3. 双向对齐：注册单元每个岗位都有职业登记；职业挂的分区/单元必须真实存在且岗位匹配。
4. 产值口径诚实：无市场口径的分区必须留 null，不得填 0 假装有数据。
5. 供给结构诚实：由成员职业 provider 实测，手写值只作对账留档。
6. 导出可用：csv/json/sqlite 三种扁平表可为制品库/知识库直接消费。
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


def test_every_occupation_anchored_to_known_partition():
    """职业要么 explicitly 未挂分区（登记的缺口），要么挂到真实存在的分区"""
    db = IndustryDatabase()
    known = {p["id"] for p in db.partitions}
    for o in db.occupations:
        uid = o.get("unit_id")
        if uid:
            assert uid in known, f"{o['id']} 的 unit_id={uid} 不存在"


def test_coverage_ratio_consistent():
    db = IndustryDatabase()
    s = db.compute()
    assert 0 < s["partition_coverage"] < 1
    assert s["covered_partitions"] == 14
    assert s["buildable_partitions"] == s["covered_partitions"] + len(db.gaps())
    # 职业基线职业全部挂到分区后覆盖率为 100%；不允许 >1 或负数
    assert 0 <= s["occupation_coverage"] <= 1
    assert s["linked_baseline_occupations"] <= s["baseline_occupations"]


def test_gdp_null_is_not_zero():
    """无市场口径的分区必须留 null，不得用 0 冒充数据"""
    db = IndustryDatabase()
    for pid in ("admin-office", "public-affairs", "international-org"):
        p = db.partition(pid)
        assert p["gdp_cny"] is None, f"{pid} 不应编造产值"
        assert "不适用" in p["gdp_source"]
    # 有产值口径的分区必须给出 scope 与 source
    for p in db.partitions:
        if p.get("gdp_cny"):
            assert p.get("gdp_scope") and p.get("gdp_source"), p["id"]


def test_provider_mix_present():
    """有成员的分区给出实测供给结构且和为 100；无成员的不给假数据"""
    db = IndustryDatabase()
    for p in db.partitions:
        if not db.members_of(p["id"]):
            continue
        mix = p["provider_mix"]
        assert set(mix) == {"ai", "hybrid", "human"}
        assert abs(sum(mix.values()) - 100) < 0.5, p["id"]


def test_provider_mix_is_measured_not_declared():
    """顶部供给结构 = 成员职业 provider 实测分布，不是手写值加权"""
    db = IndustryDatabase()
    s = db.compute()
    measured = db.provider_distribution()
    assert s["provider_mix"] == {k: measured[k] for k in ("ai", "hybrid", "human")}
    assert s["provider_mix_n"] == measured["n"]
    assert s["provider_mix_n"] == len(db.linked_occupations())
    # 不得等于「手写 provider_mix × 成员数」的加权结果（那是旧实现的错误口径）
    weighted = {"ai": 0.0, "hybrid": 0.0, "human": 0.0}
    total = 0
    for p in db.partitions:
        declared = p.get("provider_mix") or {}
        n = len(db.members_of(p["id"]))
        if not n:
            continue
        for k in weighted:
            weighted[k] += (declared.get(k) or 0) * n
        total += n
    assert s["provider_mix"] != weighted or total == 0


def test_row_provider_mix_same_source_as_summary():
    """分区行与汇总同源；手写值单独留档在 provider_mix_declared"""
    db = IndustryDatabase()
    s = db.compute()
    for r in s["rows"]:
        members = db.members_of(r["id"])
        expected = db.provider_distribution(members)
        assert r["provider_mix"] == {k: expected[k]
                                     for k in ("ai", "hybrid", "human")}, r["id"]
        assert "provider_mix_declared" in r
    # 全部行成员数之和 == 汇总样本量
    assert sum(r["member_count"] for r in s["rows"]) == s["provider_mix_n"]


def test_dangling_unit_id_is_reported():
    """职业 unit_id 指向不存在分区/单元 → validate 必须报错（不再静默放行）"""
    db = IndustryDatabase()
    db.occupations.append({"id": "ghost-occ", "name": "幽灵职业",
                           "unit_id": "ghost-unit", "unit_role": "x",
                           "provider": "ai", "billing": "usage"})
    problems = db.validate()
    assert any("ghost-occ" in p and "ghost-unit" in p for p in problems), problems


def test_dangling_occupation_excluded_from_mix():
    """悬空 unit_id 的脏数据不进供给结构分母"""
    db = IndustryDatabase()
    before = db.provider_distribution()
    db.occupations.append({"id": "ghost-occ", "name": "幽灵职业",
                           "unit_id": "ghost-unit", "unit_role": "x",
                           "provider": "ai", "billing": "usage"})
    after = db.provider_distribution()
    assert after == before


def test_declared_mix_drift_is_reported():
    """分区手写 provider_mix 与实测偏差 > 25pt → 进 problems"""
    db = IndustryDatabase()
    target = next(p for p in db.partitions if db.members_of(p["id"]))
    measured = db.provider_distribution(db.members_of(target["id"]))
    # 造一个必然漂移的声明值
    drift = 100.0 if measured["human"] < 50 else 0.0
    target["provider_mix"] = {"ai": drift, "hybrid": drift, "human": drift}
    problems = db.validate()
    assert any(target["id"] in p and "偏差" in p for p in problems), problems


def test_occupation_decoupled_from_naming():
    """职业 id 稳定，未挂分区的职业照样登记（缺漏可视）"""
    db = IndustryDatabase()
    o = db.occupation("translator")
    assert o is not None
    # 未挂分区职业可被列出
    qa = db.occupation("qa-engineer")
    assert qa is not None
    db.occupations.append({"id": "unbound-occ", "name": "未挂职业",
                           "provider": "human", "billing": "salary"})
    unassigned = {x["id"] for x in db.unassigned_occupations()}
    assert "unbound-occ" in unassigned
    # 改名不影响 id 索引
    o["name"] = "改名后的翻译"
    assert db.occupation("translator") is o


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
        # 实测列与留档列同时存在
        cols = {r[1] for r in conn.execute("pragma table_info(partition)")}
        conn.close()
        assert n_part == len(db.partitions)
        assert n_occ == len(db.occupations)
        assert row == 5
        assert {"provider_ai", "provider_ai_declared"} <= cols


def test_export_exposes_measured_and_declared_mix():
    """导出的 csv 同时给出实测列与 *_declared 留档列"""
    db = IndustryDatabase()
    with tempfile.TemporaryDirectory() as td:
        from hanghang.cli.industry_commands import cmd_industry_export

        class A:
            out = td
            format = "csv"
            data_dir = ""

        cmd_industry_export(A)
        with open(os.path.join(td, "partitions.csv"), encoding="utf-8") as fh:
            header = fh.readline().strip().split(",")
        for col in ("provider_ai", "provider_hybrid", "provider_human",
                    "provider_ai_declared", "provider_hybrid_declared",
                    "provider_human_declared"):
            assert col in header, col


def test_partition_detail_marks_estimate():
    """分区详情：无成员的待建分区供给结构标 ~ 估算，有成员的给实测"""
    import io
    from contextlib import redirect_stdout
    from hanghang.cli.industry_commands import cmd_industry_partition

    class A:
        id = "translation"
        data_dir = ""

    buf = io.StringIO()
    with redirect_stdout(buf):
        cmd_industry_partition(A)
    out = buf.getvalue()
    assert "实测" in out, out
    # 实测与对账留档同屏
    assert "对账留档" in out, out

    A.id = "mining-resources"  # evaluated 且无成员
    buf = io.StringIO()
    with redirect_stdout(buf):
        cmd_industry_partition(A)
    assert "估算~" in buf.getvalue()


if __name__ == "__main__":
    test_partition_and_occupation_loaded()
    test_members_are_derived_not_duplicated()
    test_bidirectional_alignment()
    test_every_occupation_anchored_to_known_partition()
    test_coverage_ratio_consistent()
    test_gdp_null_is_not_zero()
    test_provider_mix_present()
    test_provider_mix_is_measured_not_declared()
    test_row_provider_mix_same_source_as_summary()
    test_dangling_unit_id_is_reported()
    test_dangling_occupation_excluded_from_mix()
    test_declared_mix_drift_is_reported()
    test_occupation_decoupled_from_naming()
    test_provider_filter()
    test_export_flat_tables()
    test_export_exposes_measured_and_declared_mix()
    test_partition_detail_marks_estimate()
    print("✅ 行业分区定义库测试通过")
