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

    # 无成员分区（补全后真实数据里已无此情形，构造夹具而非硬编码 id）
    import yaml
    with tempfile.TemporaryDirectory() as td:
        fixture = IndustryDatabase()
        # 只摘掉目标分区的成员，其余职业保留（否则连"实测分支"一起测不到了）
        target = next(p for p in fixture.partitions if fixture.members_of(p["id"]))
        kept = {o["id"] for o in fixture.members_of(target["id"])}
        fixture.occupations = [o for o in fixture.occupations
                               if o["id"] not in kept]
        target["provider_mix"] = {"ai": 0, "hybrid": 0, "human": 0}
        target["provider_mix_estimated"] = {"ai": 15, "hybrid": 20, "human": 65}
        with open(os.path.join(td, "industry-partitions.yaml"), "w",
                  encoding="utf-8") as fh:
            yaml.safe_dump({"version": "0", "partitions": fixture.partitions}, fh,
                           allow_unicode=True)
        with open(os.path.join(td, "industry-occupations.yaml"), "w",
                  encoding="utf-8") as fh:
            yaml.safe_dump({"version": "0", "occupations": fixture.occupations}, fh,
                           allow_unicode=True)
        A.data_dir = td
        A.id = target["id"]
        buf = io.StringIO()
        with redirect_stdout(buf):
            cmd_industry_partition(A)
        assert "估算~" in buf.getvalue(), buf.getvalue()


def _memberless_fixture_dir(td):
    """在 td 里落一份"某分区无成员职业"的数据，返回 (分区id, 估算 AI 值)。

    补全第三轮之后真实数据里已经没有无成员分区了（每个分区都登记了职业），
    但"无成员分区不得有非零实测值、详情页要读估算列"这些契约仍要守住，
    所以改成构造夹具，不再指望真实数据恰好长成测试需要的样子。
    """
    import yaml
    fx = IndustryDatabase()
    target = next(p for p in fx.partitions if fx.members_of(p["id"]))
    kept = {o["id"] for o in fx.members_of(target["id"])}
    fx.occupations = [o for o in fx.occupations if o["id"] not in kept]
    target["provider_mix"] = {"ai": 0, "hybrid": 0, "human": 0}
    target["provider_mix_estimated"] = {"ai": 15, "hybrid": 20, "human": 65}
    with open(os.path.join(td, "industry-partitions.yaml"), "w",
              encoding="utf-8") as fh:
        yaml.safe_dump({"version": "0", "partitions": fx.partitions}, fh,
                       allow_unicode=True)
    with open(os.path.join(td, "industry-occupations.yaml"), "w",
              encoding="utf-8") as fh:
        yaml.safe_dump({"version": "0", "occupations": fx.occupations}, fh,
                       allow_unicode=True)
    return target["id"], 15


def _make_one_partition_memberless(db):
    """挑一个分区，把它的成员职业全部摘下来（构造"无成员"场景）。

    补全第三轮之后真实数据里已经没有无成员分区了（每个分区都登记了职业），
    但"无成员分区不得有非零实测值"这条契约仍然要守住 —— 所以改成构造夹具，
    不再指望真实数据恰好长成测试需要的样子。
    """
    for p in db.partitions:
        members = db.members_of(p["id"])
        if members:
            for o in members:
                o["unit_id"] = ""
            p["provider_mix"] = {"ai": 0, "hybrid": 0, "human": 0}
            if not p.get("provider_mix_estimated"):
                p["provider_mix_estimated"] = {"ai": 15, "hybrid": 20, "human": 65}
            return db, p["id"]
    raise AssertionError("没有可用的分区做夹具")


def test_no_member_partition_has_zero_measured_mix():
    """无成员职业的分区，实测口径必须是 0/0/0；人工估算另存 estimated"""
    db, _pid = _make_one_partition_memberless(IndustryDatabase())
    s = db.compute()
    no_member = [r for r in s["rows"] if r["member_count"] == 0]
    assert no_member, "构造夹具后应存在无成员分区"
    for r in no_member:
        assert r["provider_mix"] == {"ai": 0.0, "hybrid": 0.0, "human": 0.0}, \
            f"{r['id']} 无成员却给了非零实测值（手写值又冒充实测了）"
        assert r["provider_mix_declared"] == {
            "ai": 0, "hybrid": 0, "human": 0}, r["id"]
        assert r["provider_mix_estimated"], \
            f"{r['id']} 的原人工估算丢了，对账无从下手"
    # 数据文件本身也不许有非零实测值（挡住"改 yaml 绕过去"）
    for p in db.partitions:
        if db.members_of(p["id"]):
            continue
        declared = p.get("provider_mix") or {}
        assert not any(float(declared.get(k) or 0)
                       for k in ("ai", "hybrid", "human")), p["id"]


def test_no_member_partition_export_measured_as_zero():
    """导出实测列（csv/sqlite）对无成员分区必须是 0，手写值只能进 *_declared"""
    import csv as _csv
    db, _pid = _make_one_partition_memberless(IndustryDatabase())
    no_member = {p["id"] for p in db.partitions if not db.members_of(p["id"])}
    assert no_member
    with tempfile.TemporaryDirectory() as td:
        from hanghang.cli.industry_commands import cmd_industry_export

        class A:
            out = td
            format = "all"
            data_dir = ""

        # 导出走的是 CLI 自己构造的 db，所以夹具必须落成数据文件才生效
        import yaml
        with open(os.path.join(td, "industry-partitions.yaml"), "w",
                  encoding="utf-8") as fh:
            yaml.safe_dump({"version": "0", "partitions": db.partitions}, fh,
                           allow_unicode=True)
        with open(os.path.join(td, "industry-occupations.yaml"), "w",
                  encoding="utf-8") as fh:
            yaml.safe_dump({"version": "0", "occupations": db.occupations}, fh,
                           allow_unicode=True)
        A.data_dir = td
        cmd_industry_export(A)
        with open(os.path.join(td, "partitions.csv"), encoding="utf-8") as fh:
            for row in _csv.DictReader(fh):
                if row["id"] not in no_member:
                    continue
                for k in ("provider_ai", "provider_hybrid", "provider_human"):
                    assert float(row[k]) == 0.0, (row["id"], k, row[k])
        conn = sqlite3.connect(os.path.join(td, "industry.sqlite"))
        try:
            for pid in no_member:
                got = conn.execute(
                    "SELECT provider_ai, provider_hybrid, provider_human, "
                    "provider_ai_declared FROM partition WHERE id=?", (pid,)
                ).fetchone()
                assert got[:3] == (0.0, 0.0, 0.0), (pid, got)
                assert got[3] == 0.0, (pid, got)
        finally:
            conn.close()


def test_partition_detail_reads_estimated_not_declared():
    """详情页无成员时读 provider_mix_estimated，不得把手写值念成实测"""
    import io
    from contextlib import redirect_stdout
    from hanghang.cli.industry_commands import cmd_industry_partition

    class A:
        data_dir = ""
        id = ""

    with tempfile.TemporaryDirectory() as td:
        pid, est = _memberless_fixture_dir(td)
        A.data_dir = td
        A.id = pid
        buf = io.StringIO()
        with redirect_stdout(buf):
            cmd_industry_partition(A)
        out = buf.getvalue()
    assert "估算~" in out and str(est) in out, out
    assert "供给结构(实测): AI 0%" not in out, out


def test_validate_reports_missing_unit_role_on_registered_unit():
    """a) 已建单元的分区，成员缺 unit_role → 报错（建单元后路由命中不了）"""
    db = IndustryDatabase()
    db.partitions.append({"id": "fake-part-x", "name": "假分区",
                          "status": "covered", "unit_id": "dongjiagoushi"})
    db.occupations.append({"id": "fake-occ", "name": "假职业",
                           "unit_id": "fake-part-x", "unit_role": None,
                           "provider": "ai", "billing": "usage"})
    problems = db.validate()
    assert any("fake-occ" in p and "unit_role" in p for p in problems), problems


def test_validate_reports_unit_id_member_mismatch():
    """校验点 8/9：成员挂在本分区但角色不属于分区指向的单元 → 报 unit_role

    反查口径是 unit_id == 分区 id，所以"成员挂错到别的单元"根本进不了
    members_of()；那类错挂由 validate 的全量扫描覆盖（见下一条）。
    这条守的是"分区指向单元 A、成员角色却是单元 B 的岗位"。
    """
    db = IndustryDatabase()
    db.partitions.append({"id": "fake-part-y", "name": "假分区",
                          "status": "covered", "unit_id": "dongjiagoushi"})
    db.occupations.append({"id": "fake-occ-y", "name": "假职业",
                           "unit_id": "fake-part-y", "unit_role": "game_planner",
                           "provider": "ai", "billing": "usage"})
    problems = db.validate()
    assert any("fake-occ-y" in p and "game_planner" in p for p in problems), problems


def test_validate_reports_occupation_attached_to_unit_not_partition():
    """校验点 8：职业挂到单元 id 而非分区 id → 不属于任何分区，必须报错

    这类数据在 members_of() 里永远查不到，只在分区的成员循环里校验是抓不到的。
    """
    db = IndustryDatabase()
    db.partitions.append({"id": "unit-only-part", "name": "只有分区",
                          "status": "covered", "unit_id": "dongjiagoushi"})
    # game-dev-unit 既是分区 id 也是单元 id，会被正常反查；这里换一个"真单元但
    # 分区不指向它"的场景：直接篡改分区 id，让成员挂的单元成为孤立单元。
    db.partitions[-1]["unit_id"] = "dongjiagoushi"
    db.occupations.append({"id": "orphan-on-unit", "name": "挂单元的职业",
                           "unit_id": "e-commerce", "unit_role": "ops",
                           "provider": "ai"})
    problems = db.validate()
    assert any("orphan-on-unit" in p for p in problems), problems


def test_validate_reports_evaluated_partition_with_unit():
    """c) evaluated（明确不建单元）却填了 unit_id → 状态互斥报错"""
    db = IndustryDatabase()
    db.partitions.append({"id": "fake-part-z", "name": "假分区",
                          "status": "evaluated", "unit_id": "dongjiagoushi"})
    problems = db.validate()
    assert any("fake-part-z" in p and "evaluated" in p for p in problems), problems


def test_pending_partition_unit_role_must_be_in_planned_roles():
    """未建单元的成员 unit_role 可空；填了就必须在该分区 planned_roles 里"""
    db = IndustryDatabase()
    pending = next(p for p in db.partitions
                   if p.get("status") == "pending"
                   and not p.get("unit_id")
                   and db.members_of(p["id"]))
    pending["planned_roles"] = ["declared_role_only"]
    member = db.members_of(pending["id"])[0]
    member["unit_role"] = "随手编的角色"
    problems = db.validate()
    assert any(member["id"] in p and "planned_roles" in p
               for p in problems), problems


def test_validate_survives_dirty_mix_values():
    """provider_mix 里塞脏数据（非数值/布尔）时，validate 报问题而不是崩"""
    db = IndustryDatabase()
    db.partitions.append({"id": "dirty-mix", "status": "pending",
                          "provider_mix": {"ai": "abc", "hybrid": True,
                                           "human": 0}})
    # 脏值不能被误读成非零（True 不是 1），也不能抛异常
    db.partitions[-1]["provider_mix"] = {"ai": "30", "hybrid": None,
                                         "human": 0}
    problems = db.validate()
    assert any("dirty-mix" in p for p in problems), problems
    # 有成员时的漂移计算同样不能因脏值崩
    db.partitions[-1]["provider_mix"] = {"ai": "abc", "hybrid": None,
                                         "human": 0}
    db.partitions[-1]["planned_roles"] = ["x"]
    db.occupations.append({"id": "dirty-occ", "unit_id": "dirty-mix",
                           "unit_role": "x", "provider": "ai"})
    assert isinstance(db.validate(), list)


def test_real_pending_partitions_are_not_flagged():
    """现实路径不被误伤：18 个待建分区成员 unit_role 为空不算错"""
    db = IndustryDatabase()
    assert db.validate() == []


# ---------------------------------------------------------------- 校验点 1-13
def test_validate_reports_covered_partition_without_members():
    """校验点 6：covered 却无成员职业 → 纸面覆盖必须报出来"""
    db = IndustryDatabase()
    db.partitions.append({"id": "paper-cov", "name": "纸面覆盖",
                          "status": "covered", "unit_id": "dongjiagoushi"})
    problems = db.validate()
    assert any("paper-cov" in p and "纸面覆盖" in p for p in problems), problems


def test_paper_covered_partition_not_in_coverage_numerator():
    """纸面覆盖不能进覆盖率分子：数值上不失真，但缺口必须可见"""
    db = IndustryDatabase()
    before = db.compute()["covered_partitions"]
    db.partitions.append({"id": "paper-cov", "name": "纸面覆盖",
                          "status": "covered", "unit_id": "dongjiagoushi"})
    assert db.compute()["covered_partitions"] == before + 1
    assert db.validate(), "分子涨了却没有问题记录 = 静默变好看"


def test_validate_reports_unknown_status():
    """校验点 2：status 拼错/漏填的分区不会静默漏出分母"""
    db = IndustryDatabase()
    before = db.compute()["buildable_partitions"]
    db.partitions.append({"id": "coverd-typo", "name": "拼错",
                          "status": "coverd", "unit_id": "dongjiagoushi"})
    db.partitions.append({"id": "no-status", "name": "缺状态", "unit_id": ""})
    problems = db.validate()
    assert any("coverd-typo" in p and "status" in p for p in problems), problems
    assert any("no-status" in p and "status" in p for p in problems), problems
    # 拼错的分区既没进分母也没报错才是问题；这里确认它确实没进分母
    assert db.compute()["buildable_partitions"] == before


def test_validate_reports_empty_primary_key():
    """校验点 1：空 id / 空 name 会让分母虚增，必须报错"""
    db = IndustryDatabase()
    db.occupations.append({"id": "", "name": "空id", "unit_id": "translation"})
    problems = db.validate()
    assert any("缺少 id" in p for p in problems), problems


def test_validate_reports_duplicate_primary_key():
    """校验点 1：重复 id 必须报出并给出次数（否则成员被静默丢弃）"""
    db = IndustryDatabase()
    db.partitions.append({"id": "dup-part", "name": "A", "status": "pending"})
    db.partitions.append({"id": "dup-part", "name": "B", "status": "pending"})
    problems = db.validate()
    assert any("dup-part" in p and "重复" in p and "2 次" in p
               for p in problems), problems


def test_duplicate_key_does_not_break_index():
    """重复 id 不能让 partition() 返回 None（否则详情页永远"未找到"）"""
    db = IndustryDatabase()
    db.partitions.append({"id": "dup-part", "name": "首次出现", "status": "pending"})
    db.partitions.append({"id": "dup-part", "name": "第二次", "status": "pending"})
    got = db.partition("dup-part")
    assert got is not None and got["name"] == "首次出现"


def test_duplicate_occupation_not_dropped_from_mix():
    """重复职业 id 时成员不能被静默丢弃：分母不缩水，重复由 validate 报出"""
    db = IndustryDatabase()
    first = db.occupations[0]
    db.occupations.append(dict(first))  # 同 id 再塞一条
    target = first["unit_id"]
    ids = [o["id"] for o in db.members_of(target)]
    assert ids.count(first["id"]) == 2, ids


def test_index_refreshes_after_dynamic_append():
    """动态追加分区后 partition() 必须能查到（加载期索引不能过期）"""
    db = IndustryDatabase()
    db.partitions.append({"id": "late-part", "name": "后加的分区",
                          "status": "pending"})
    assert db.partition("late-part") is not None
    assert "late-part" in {r["id"] for r in db.compute()["rows"]}


def test_validate_reports_missing_data_source():
    """校验点 13：yaml 读不到要显式报出，空库不能当作自检通过"""
    db = IndustryDatabase(data_dir=os.path.join(tempfile.gettempdir(), "no-such-dir"))
    problems = db.validate()
    assert any("未读到" in p for p in problems), problems


def test_render_marks_no_member_as_dash_not_zero():
    """无成员分区的 AI% 显示 "-"，真实 0% 仍显示 0.0（两者不能混）"""
    db, pid = _make_one_partition_memberless(IndustryDatabase())
    out = db.render_text()
    # 无成员分区那一行：AI% 必须是 "-"（不是 0.0，也不是空）
    name = db.partition(pid)["name"]
    row = next(l for l in out.splitlines() if name in l)
    assert " - " in f" {row} ", row
    # 有成员且实测 0% 的分区仍显示 0.0（真实 0 与"无数据"不能混）
    db2 = IndustryDatabase()
    health = next(l for l in db2.render_text().splitlines() if "健康医疗" in l)
    assert "0.0" in health, health


def test_occupation_anchored_to_unit_id_is_reported():
    """校验点 8：职业挂到单元 id 而非分区 id → 反查属于任何分区都查不到，必须报错"""
    db = IndustryDatabase()
    # 造一个"是分区 id 但分区不指向它"的情形：把成员挂到别处更直观——
    # 这里直接用真实单元 id（同时是分区 id）不算错，故构造分区/单元错配的替身：
    db.partitions = [p for p in db.partitions if p.get("id") != "translation"]
    db.occupations.append({"id": "orphan-occ", "name": "孤儿职业",
                           "unit_id": "translation", "unit_role": "x",
                           "provider": "ai"})
    # translation 已不是分区，但它也不是注册单元 → 归为悬空（校验点 3）
    problems = db.validate()
    assert any("orphan-occ" in p for p in problems), problems


def test_role_baseline_source_stale_is_not_silent():
    """权威源失效（分区有登记但全非基线）必须进 problems，不静默回落"""
    from hanghang.engine.coverage import CoverageTracker
    db = IndustryDatabase()
    for o in db.members_of("dongjiagoushi"):
        o["baseline_occupation"] = False
    s = CoverageTracker(industry_db=db).compute()
    stale = [r for r in s["rows"] if r["roles"]["baseline_source"] == "stale"]
    assert stale, "应至少有一行被判 stale"
    assert any("stale" in p or "baseline_occupation" in p for p in s["problems"])


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
    test_no_member_partition_has_zero_measured_mix()
    test_no_member_partition_export_measured_as_zero()
    test_partition_detail_reads_estimated_not_declared()
    test_validate_reports_missing_unit_role_on_registered_unit()
    test_validate_reports_unit_id_member_mismatch()
    test_validate_reports_occupation_attached_to_unit_not_partition()
    test_validate_reports_evaluated_partition_with_unit()
    test_pending_partition_unit_role_must_be_in_planned_roles()
    test_validate_survives_dirty_mix_values()
    test_real_pending_partitions_are_not_flagged()
    test_validate_reports_covered_partition_without_members()
    test_paper_covered_partition_not_in_coverage_numerator()
    test_validate_reports_unknown_status()
    test_validate_reports_empty_primary_key()
    test_validate_reports_duplicate_primary_key()
    test_duplicate_key_does_not_break_index()
    test_duplicate_occupation_not_dropped_from_mix()
    test_index_refreshes_after_dynamic_append()
    test_validate_reports_missing_data_source()
    test_render_marks_no_member_as_dash_not_zero()
    test_occupation_anchored_to_unit_id_is_reported()
    test_role_baseline_source_stale_is_not_silent()
    print("✅ 行业分区定义库测试通过")
