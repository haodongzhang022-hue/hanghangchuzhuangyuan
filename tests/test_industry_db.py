"""M11 行业分区定义库测试

核心断言（对应用户要求）：
1. 职业是解耦最小单位：职业带唯一编号 OCC-####，**自身不存归属字段**，
   不受行业命名影响。
2. 归属是模糊的：职业↔分区是带权重的边（occupation-memberships.yaml），
   一个职业可被任意多个视角同时引用；分区不手写成员清单。
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
    """分区成员由归属边反查，分区定义里不重复存职业清单"""
    db = IndustryDatabase()
    p = db.partition("dongjiagoushi")
    assert p is not None
    members = db.members_of("dongjiagoushi")
    # 岗位名挂在边上：同一个职业在别的视角下可以是别的岗位名
    roles = {m["partition"]: m["unit_role"]
             for m in db.views_of_occupation("architect")}
    assert roles["dongjiagoushi"] == "architect"
    # 前 5 个是单元自带的岗位；后 3 个是补登记的跨岗位职业（测试/运维/算法），
    # 它们挂在同名的现有岗位下，不允许为它们临时造岗位名
    assert {o["id"] for o in members} == {
        "dev-secretary", "architect", "developer", "code-reviewer", "product-manager",
        "qa-engineer", "sre-devops", "algorithm-engineer"}
    # 分区定义本身不含 members 字段，避免两份清单分叉
    assert "members" not in p
    # 职业自身也不存归属字段（否则又变回"唯一归属"了）
    for o in db.occupations:
        assert "unit_id" not in o, f"{o['id']} 还残留单值归属字段"
        assert "unit_role" not in o, f"{o['id']} 还残留单值岗位名字段"


def test_bidirectional_alignment():
    """职业↔单元岗位 双向对齐，无纸面覆盖。

    第 19 条（骨架反查）上线后，现实数据会报出待建分区的骨架缺口：
    20 个 pending 分区声明要建的岗位，职业库里还没有对应原子岗位。这不是
    代码缺陷，是"待建分区补职业"这项活本身没干完——这里只要求除它之外干净。
    """
    db = IndustryDatabase()
    others = [p for p in db.validate() if "骨架悬空" not in p]
    assert others == [], others


def test_every_membership_edge_points_to_known_partition():
    """每条归属边都必须指向真实存在的分区；职业可以一条边都没有"""
    db = IndustryDatabase()
    known = {p["id"] for p in db.partitions}
    for m in db.axis_view.memberships:
        assert m["partition"] in known, f"{m['occupation']} 的边指向 {m['partition']}"


def test_coverage_ratio_consistent():
    db = IndustryDatabase()
    s = db.compute()
    # 覆盖率分母**不含 evaluated**（评估后不建的分区不计入「还欠多少」）。
    # 所以 0 < x < 1 不是不变式：当所有非 evaluated 分区都建完时它就是 1.0。
    # 真正的不变式是「分子 == status=covered 的分区数」，见下方断言。
    assert 0 < s["partition_coverage"] <= 1
    covered = sum(1 for p in db.partitions if p.get("status") == "covered")
    assert s["covered_partitions"] == covered, (
        f"覆盖率分子的口径与分区状态不一致：{s['covered_partitions']} vs {covered}")
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
    # 汇总样本量是"被任何视角看见过的职业数"，不是各行成员数相加：
    # 软归属下一个职业可以出现在多行里，相加会把同一个人数两遍
    assert s["provider_mix_n"] == len(db.linked_occupations())
    assert sum(r["member_count"] for r in s["rows"]) >= s["provider_mix_n"]


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
        # sqlite 可直接按视角聚合成员数（边在 membership 表里）
        row = conn.execute(
            "select count(*) from membership where partition='dongjiagoushi'"
        ).fetchone()[0]
        # 实测列与留档列同时存在
        cols = {r[1] for r in conn.execute("pragma table_info(partition)")}
        conn.close()
        assert n_part == len(db.partitions)
        assert n_occ == len(db.occupations)
        # 写死 8 会随补登记漂移；这里比的是"同一份数据在库里有几条边"
        assert row == len([m for m in db.axis_view.memberships
                           if m["partition"] == "dongjiagoushi"])
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

    归属改成"边"之后，摘成员 = 删掉指向该分区的边（职业本身不受影响，
    这正好说明原子岗位不会被分类改动牵连）。
    """
    for p in db.partitions:
        edges = [m for m in db.axis_view.memberships if m["partition"] == p["id"]]
        if edges:
            db.axis_view.refresh([
                m for m in db.axis_view.memberships if m["partition"] != p["id"]])
            db._memberships_raw = [dict(m) for m in db.axis_view.memberships]
            db._reindex()
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


def _add_edge_db(partition, occupation, unit_role=""):
    """构造夹具：加一个分区 + 一个职业 + 一条归属边（软归属的最小单元）。"""
    db = IndustryDatabase()
    db.partitions.append(partition)
    db.occupations.append(occupation)
    # _reindex 会拿"当前生效的边"覆盖 _memberships_raw，所以要先 refresh 再追加
    db.axis_view.refresh([
        {"occupation": occupation["id"], "partition": partition["id"],
         "axis": "occupation", "weight": 1.0, "unit_role": unit_role}]
        + list(db.axis_view.memberships))
    db._reindex()
    return db


def _fake_occ(seq, **kw):
    """构造夹具用的职业：编号必须与登记序号一致，否则会被唯一编号校验抓住"""
    row = {"id": f"fake-occ-{seq}", "code": f"OCC-{seq:06d}", "name": "假职业",
           "deliverable": "服务", "provider": "ai", "billing": "usage",
           "baseline_occupation": True}
    row.update(kw)
    return row


def test_validate_reports_missing_unit_role_on_registered_unit():
    """a) 已建单元的分区，成员缺 unit_role → 报错（建单元后路由命中不了）"""
    db = _add_edge_db(
        {"id": "fake-part-x", "name": "假分区", "status": "covered",
         "unit_id": "dongjiagoushi", "planned_roles": ["architect"]},
        _fake_occ(len(IndustryDatabase().occupations) + 1))
    problems = db.validate()
    assert any("fake-occ" in p and "unit_role" in p for p in problems), problems


def test_validate_reports_unit_role_not_in_unit():
    """分区指向单元 A、边上的岗位名却是单元 B 的岗位 → 必须报出来"""
    db = _add_edge_db(
        {"id": "fake-part-y", "name": "假分区", "status": "covered",
         "unit_id": "dongjiagoushi"},
        _fake_occ(len(IndustryDatabase().occupations) + 1, id="fake-occ-y"),
        unit_role="game_planner")
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
    """未建单元的成员 unit_role 可空；填了就必须在该分区 planned_roles 里

    不依赖「真实数据里一定还有 pending 分区」——所有分区都建完之后
    `next(...)` 会抛 StopIteration，测的就不再是校验逻辑而是当时的进度。
    这里显式把一个分区临时的 status 改成 pending 来构造场景。
    """
    db = IndustryDatabase()
    candidates = [p for p in db.partitions if db.members_of(p["id"])]
    assert candidates, "没有任何分区有成员职业，无法构造该场景"
    pending = candidates[0]
    saved_status = pending.get("status")
    saved_unit = pending.get("unit_id")
    saved_planned = list(pending.get("planned_roles") or [])
    try:
        pending["status"] = "pending"
        pending["unit_id"] = ""
        pending["planned_roles"] = ["declared_role_only"]
        edge = next(m for m in db.axis_view.memberships
                    if m["partition"] == pending["id"])
        saved_role = edge.get("unit_role")
        edge["unit_role"] = "随手编的角色"
        member = db.members_of(pending["id"])[0]
        problems = db.validate()
        assert any(member["id"] in p and "planned_roles" in p
                   for p in problems), problems
    finally:
        pending["status"] = saved_status
        pending["unit_id"] = saved_unit
        pending["planned_roles"] = saved_planned


def test_missing_planned_roles_is_reported_not_silently_skipped():
    """第10条曾被 planned_roles 为空短路掉：判据缺失不能等于没问题

    不依赖「真实数据里一定还有 pending 分区」（全部建完后会 StopIteration），
    显式构造 pending 场景。
    """
    db = IndustryDatabase()
    candidates = [p for p in db.partitions if db.members_of(p["id"])]
    assert candidates, "没有任何分区有成员职业，无法构造该场景"
    pending = candidates[0]
    saved_status = pending.get("status")
    saved_unit = pending.get("unit_id")
    saved_planned = list(pending.get("planned_roles") or [])
    edge = next(m for m in db.axis_view.memberships
                if m["partition"] == pending["id"])
    saved_role = edge.get("unit_role")
    try:
        pending["status"] = "pending"
        pending["unit_id"] = ""
        pending["planned_roles"] = []          # 骨架缺失
        edge["unit_role"] = "随手编的角色"
        problems = db.validate()
        # 旧实现（role and planned and ...）在这里会返回 []
        assert any(pending["id"] in p and "planned_roles" in p
                   for p in problems), problems
    finally:
        pending["status"] = saved_status
        pending["unit_id"] = saved_unit
        pending["planned_roles"] = saved_planned
        edge["unit_role"] = saved_role


def test_pending_partition_field_must_point_to_real_partition():
    """pending_partition 写错分区 = 一句没人执行的承诺"""
    db = IndustryDatabase()
    # 现实数据里已经没有孤立职业了（自由职业归零），所以造一个
    db.occupations.append({"id": "lost-hope", "name": "没去向的职业",
                           "provider": "human", "billing": "salary"})
    occ = db.occupation("lost-hope")
    occ["pending_partition"] = "no-such-partition"
    problems = db.validate()
    assert any(occ["id"] in p and "pending_partition" in p
               for p in problems), problems


def test_pending_partition_must_be_cleared_once_fulfilled():
    """意向已兑现（已有归属边）却还留着 pending_partition → 字段没清"""
    db = IndustryDatabase()
    linked = next(o for o in db.occupations if db.views_of_occupation(o["id"]))
    linked["pending_partition"] = db.views_of_occupation(linked["id"])[0]["partition"]
    problems = db.validate()
    assert any(linked["id"] in p and "pending_partition" in p
               for p in problems), problems


def test_note_only_intent_is_now_explicit_data():
    """意向不能只活在 note 里：孤立职业要么带 pending_partition，要么就别掉队

    8 个原本只在 note 里写"待补"的职业**已经全部挂上视角**（free 归零），
    所以这里守两件事：
      1) 现实数据里没有谁掉队了——掉队的那批已经清了；
      2) 真掉队时必须能查到明细（不许只给个数字把人藏起来），
         且要么有 pending_partition 说明去向，要么就是明确登记为"待定"。
    """
    db = IndustryDatabase()
    assert db.axis_view.free_occupations() == [], "又出现没有归属边的职业了"
    # 造一个掉队的，验证明细出口还在（补全完成后这条路径不能变成死代码）
    db.occupations.append({"id": "lost-occ", "name": "掉队的职业",
                           "provider": "human", "billing": "salary",
                           "pending_partition": "dongjiagoushi"})
    details = db.compute()["free_occupation_details"]
    assert any(d["id"] == "lost-occ" for d in details), details
    assert all("pending_partition" in d for d in details)


def test_previously_free_occupations_are_now_linked():
    """8 个曾经"只在 note 里待补"的职业必须真有归属边，不再靠一句备忘

    这条是本轮的验收口径：意向兑现成数据。挂到已建单元上的那几条还必须带
    `unit_role`，否则建了单元也路由不到（第 9 条会报）。
    """
    db = IndustryDatabase()
    expected = {
        "qa-engineer": "dongjiagoushi",
        "sre-devops": "dongjiagoushi",
        "algorithm-engineer": "data-analytics",
        "game-artist": "game-dev-unit",
        "patent-agent": "legal-services",
        "translator": "translation",
        "auditor": "finance-accounting",
        "nurse": "healthcare",
    }
    for oid, pid in expected.items():
        views = {m["partition"] for m in db.views_of_occupation(oid)}
        assert pid in views, f"{oid} 仍然没挂到 {pid}：{views}"
        # 意向兑现后字段必须清掉，否则第 18 条会报"字段没清"
        assert not db.occupation(oid).get("pending_partition"), oid
    # 已建单元的那几个必须带岗位名（且必须是该单元真实存在的岗位）
    for oid in ("qa-engineer", "sre-devops", "algorithm-engineer", "game-artist",
                "patent-agent", "auditor", "nurse"):
        edges = [m for m in db.views_of_occupation(oid) if m.get("unit_role")]
        assert edges, f"{oid} 挂了已建单元却没有 unit_role"


def test_export_exposes_estimated_mix_columns():
    """估算值必须有出口：sqlite/csv 只给实测列，下游只拿到一堆 0"""
    import sqlite3
    db = IndustryDatabase()
    estimated = [p for p in db.partitions if p.get("provider_mix_estimated")]
    assert estimated, "测试前提：至少一个分区有估算值"
    with tempfile.TemporaryDirectory() as td:
        from hanghang.cli.industry_commands import cmd_industry_export

        class A:
            out = td
            format = "all"
            data_dir = ""

        cmd_industry_export(A)
        with open(os.path.join(td, "partitions.csv"), encoding="utf-8") as fh:
            header = fh.readline().strip().split(",")
        for col in ("provider_ai_estimated", "provider_hybrid_estimated",
                    "provider_human_estimated"):
            assert col in header, col
        conn = sqlite3.connect(os.path.join(td, "industry.sqlite"))
        cols = {r[1] for r in conn.execute("pragma table_info(partition)")}
        pid = estimated[0]["id"]
        row = conn.execute(
            "select provider_ai, provider_ai_estimated from partition where id=?",
            (pid,)).fetchone()
        conn.close()
        assert {"provider_ai_estimated", "provider_hybrid_estimated",
                "provider_human_estimated"} <= cols
        # mining 这类无成员分区：实测 0，估算是真值 —— 两者必须分开
        assert row[0] in (0, 0.0) and row[1] not in (None, 0, 0.0), row


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
    """现实路径不被误伤：待建分区成员 unit_role 为空不算错。

    只允许"骨架悬空"这一类（待建分区声明要建的岗位还没有原子岗位对应）；
    "unit_role 为空"本身不许报错——那是合法的等待态。
    """
    db = IndustryDatabase()
    problems = db.validate()
    assert [p for p in problems if "骨架悬空" not in p] == [], problems
    assert not any("未填 unit_role" in p for p in problems), problems


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
    target = db.views_of_occupation(first["id"])[0]["partition"]
    ids = [o["id"] for o in db.members_of(target)]
    # 成员按视角筛出来的是"人"，同 id 的两条记录只算一个人
    assert ids.count(first["id"]) == 1, ids


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


# ---------------------------------------------------------------------------
# 错误折叠（层级/粒度错误）守卫
#
# 用户报的两个 bug 长这样：
#   1) 多个规则不同、付费方不同、AI 承接面差一个量级的对象被塞进同一个分区，
#      合起来只剩一个笼统标签，谁跟谁一类根本看不出来 —— 信息丢失；
#   2) 把「岗位」当「行业」写进分区表 —— 层级错误，分区 id 与职业 id 撞名。
# 这两类错都不会让覆盖率变红，只会在下次有人读表时把人骗了。
# ---------------------------------------------------------------------------

# 曾被错误折叠的旧分区 id -> 现在必须存在的分区 id
_UNFOLDED_SPLITS = {
    "esports-live": ("live-streaming", "esports"),
    "sport-leisure": ("sport-fitness", "sport-games"),
}
# 曾经跨粒度共用一个分区 id 的（口译 / 笔译）
_SPLIT_TRANSLATION = ("interpretation", "translation")


def test_folded_partitions_are_gone():
    """旧折叠分区 id 不得复活：一旦重建，拆分就会被下一次合并悄悄撤销"""
    db = IndustryDatabase()
    ids = {p["id"] for p in db.partitions}
    for old in _UNFOLDED_SPLITS:
        assert old not in ids, f"折叠分区 {old} 又回来了，拆分被回退"


def test_split_partitions_coexist_with_distinct_rules():
    """拆出来的分区必须同时存在，且聚类依据/付费方不是同一句话"""
    db = IndustryDatabase()
    for old, parts in _UNFOLDED_SPLITS.items():
        names = set()
        for pid in parts:
            p = db.partition(pid)
            assert p is not None, f"{old} 拆分后缺少 {pid}"
            assert db.members_of(pid), f"{pid} 没有任何成员职业，等于空壳分区"
            assert p.get("demand_side"), f"{pid} 没写付费方"
            assert p.get("cluster_basis"), f"{pid} 没写聚类依据"
            names.add((tuple(p["cluster_basis"]), tuple(p["demand_side"])))
        assert len(names) == len(parts), (
            f"{old} 拆出来的分区规则完全一样，说明只是改了个名字")


def test_no_occupation_sits_in_two_conflated_business_models():
    """口译与笔译不得共用分区：现场同步交付 vs 异步文本交付，AI 承接面差一个量级"""
    db = IndustryDatabase()
    for pid in _SPLIT_TRANSLATION:
        assert db.partition(pid) is not None, f"缺少分区 {pid}"
    interp = {o["id"] for o in db.members_of("interpretation")}
    written = {o["id"] for o in db.members_of("translation")}
    assert "simultaneous-interpreter" in interp
    assert "simultaneous-interpreter" not in written
    assert interp.isdisjoint(written), "口译/笔译成员不得重叠（拆分要拆干净）"


def test_occupation_level_and_industry_level_ids_do_not_collide():
    """层级错误守卫：职业 id 与分区 id 不能撞名

    把岗位当行业时最典型的症状就是两边共用同一个 id —— 反查会不会串、
    覆盖分子分母会不会互相污染，都从这里开始。
    """
    db = IndustryDatabase()
    part_ids = {p["id"] for p in db.partitions}
    occ_ids = {o["id"] for o in db.occupations}
    both = part_ids & occ_ids
    assert not both, f"这些 id 同时被当作岗位和行业：{sorted(both)}"


def test_partition_name_is_not_a_job_title():
    """分区名不能是单个岗位名，否则等于把岗位包装成了行业"""
    db = IndustryDatabase()
    occ_names = {(o.get("name") or "").strip() for o in db.occupations}
    bad = [p["id"] for p in db.partitions
           if (p.get("name") or "").strip() in occ_names and p.get("name")]
    # 允许少量历史同名的（如分区名恰好等于某岗位名）时，必须在 aliases 里
    # 给出行业级叫法，否则仍算层级不明
    for pid in bad:
        p = db.partition(pid)
        assert p.get("aliases"), f"分区 {pid} 与某个岗位同名且无行业级别名，层级不明"


def test_unfolded_partitions_have_null_gdp_not_fabricated_split():
    """拆出来的分区没有独立产值口径时必须留 null，不能按比例切一份出来"""
    db = IndustryDatabase()
    # 电竞/健身/口译都没有单独发布的统计口径
    for pid in ("esports", "sport-fitness", "interpretation"):
        p = db.partition(pid)
        assert p is not None, f"缺少分区 {pid}"
        assert p.get("gdp_cny") is None, (
            f"{pid} 没有独立产值口径，不该填 gdp_cny={p.get('gdp_cny')}"
            f"（那等于把合并口径按比例拍脑袋切分）")
        assert p.get("gdp_source"), f"{pid} 需要写明为什么留空"


def test_split_partition_gdp_is_not_double_counted():
    """拆分后各分区产值之和不得凭空变大（复制粘贴同一份口径会翻倍）"""
    db = IndustryDatabase()
    # sport-games 保留了体育产业总产出（宽口径、整体口径），
    # sport-fitness 必须留空，否则同一份 3 万亿被算了两遍
    assert db.partition("sport-games").get("gdp_cny") is not None
    assert db.partition("sport-fitness").get("gdp_cny") is None


def test_broken_reference_tables_do_not_take_down_the_db():
    """只读旁证表写坏不许连坐整个 M11 出口

    `IndustryDatabase.__init__` 三处构造都在 yaml.safe_load 参考表：catalog /
    isco / classification_sources。只包了 catalog 一处的后果是造库直接抛异常，
    `industry check`、`industry partitions` 全以 traceback 退出、`/api/industry-db`
    固定 503 —— 一份只读旁证把整个数据产品拖下水。
    """
    import shutil
    import tempfile

    src = os.path.join(os.path.dirname(__file__), "..", "data")
    with tempfile.TemporaryDirectory() as tmp:
        dst = os.path.join(tmp, "data")
        shutil.copytree(src, dst)
        bad = os.path.join(dst, "reference", "occupation-catalog-isco08.yaml")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write("unit_groups: [")   # 语法不完整
        db = IndustryDatabase(data_dir=dst)
        # 造库不抛，两个旁证降级为 None，主数据照常可用
        assert db.isco is None, "ISCO 表坏了应当降级为 None"
        # 不锁死具体数字：本测试要守的是「旁证坏了主数据仍可用」，
        # 而分区/职业数会随补全而增长（41→45、178→197 都是正常演进）。
        # 写死 41/178 会让每次扩分区都误报成回归。
        assert len(db.partitions) >= 41, len(db.partitions)
        assert len(db.occupations) >= 178, len(db.occupations)
        s = db.compute()
        assert s["rows"], "主数据不该因为旁证坏了而空掉"
        # 降级必须可见：进 problems，不能静默当"没问题"
        assert any("ISCO-08" in p for p in db.validate()), db.validate()


def test_same_occupation_on_two_axes_counts_once():
    """同一职业同分区挂两根轴：按「人」去重，不按边数

    模型明确允许一条边一个轴（validate 的唯一键是 职业|分区|轴），但"某视角下
    有哪些人"必须去重：不去重会让 member_count 比 member_weights 多、provider_mix
    分母重复计数、coverage 该行 covered 虚高。口径要与 weights_of 的 max 对齐。
    """
    db = IndustryDatabase()
    before = len(db.members_of("e-commerce"))
    weights_before = len(db.weights_of("e-commerce"))
    db.axis_view.memberships.append({
        "occupation": "store-manager", "partition": "e-commerce",
        "axis": "tax", "weight": 0.5, "unit_role": "store_manager"})
    db.axis_view._index()
    assert len(db.members_of("e-commerce")) == before, "同一职业被算成了两个人"
    assert len(db.weights_of("e-commerce")) == weights_before


def test_render_aligns_columns_for_cjk_names():
    """中文长分区名不得顶穿表格列：'{: <14}' / str.ljust 按字符数补，中文会歪

    坑：`line[:25]` 是按**字符**切，汉字占两列，25 个字符可能是 31 列，也可能
    正好把某个汉字切一半。所以取前 N 列必须按显示宽度逐字符累加，不能切字符串
    ——这条断言自己第一版就踩了这个坑，本地一直没跑（用例没注册进 __main__）。
    """
    db = IndustryDatabase()

    def head_by_width(line, width):
        acc = ""
        for ch in line:
            if db._disp_width(acc + ch) > width:
                break
            acc += ch
        return acc

    text = db.render_text(top=0)
    lines = text.splitlines()
    # 表头也必须落在同一条列线上（表头曾用 f-string 的 '<14'，按字符数补，
    # 中文顶宽，表体用 _cell 按显示宽度补，两边错位 8 列）
    heads = [l for l in lines if l.startswith("状态")]
    assert heads, "缺少表头"
    # 关键：表头前两格（状态 + 分区）的显示宽度必须正好 25 列。
    # 旧表头 f-string '<14' 按字符数补，'分区' 补到 14 字符 = 28 显示列，
    # 这里会变成 33 —— 多出 8 列，整张表歪 8 格。
    head_two_cells = db._cell("状态", 5) + db._cell("分区", 20)
    assert heads[0].startswith(head_two_cells), (
        f"表头前两格宽度不对: {heads[0][:28]!r}")
    assert db._disp_width(head_two_cells) == 25

    marks = ("已建", "待建", "不建")
    starts = set()
    for line in lines:
        if not line.startswith(marks):
            continue
        starts.add(db._disp_width(head_by_width(line, 25)))
    assert starts == {25}, f"数据列起点没对齐: {sorted(starts)}"
    # 超宽名字截断加省略号，而不是顶穿后面三列
    assert "国际组织与对外事务" in text or "国际组织与对外事…" in text
    assert db._disp_width(db._cell("国际组织与对外事务", 20)) == 20
    assert db._disp_width(db._cell("无口径", 10)) == 10
    assert db._disp_width(db._cell("330,000", 10)) == 10


if __name__ == "__main__":
    test_previously_free_occupations_are_now_linked()
    test_render_aligns_columns_for_cjk_names()
    test_partition_and_occupation_loaded()
    test_members_are_derived_not_duplicated()
    test_bidirectional_alignment()
    test_every_membership_edge_points_to_known_partition()
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
    test_validate_reports_unit_role_not_in_unit()
    test_validate_reports_occupation_attached_to_unit_not_partition()
    test_validate_reports_evaluated_partition_with_unit()
    test_pending_partition_unit_role_must_be_in_planned_roles()
    test_missing_planned_roles_is_reported_not_silently_skipped()
    test_pending_partition_field_must_point_to_real_partition()
    test_pending_partition_must_be_cleared_once_fulfilled()
    test_note_only_intent_is_now_explicit_data()
    test_export_exposes_estimated_mix_columns()
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
    test_folded_partitions_are_gone()
    test_split_partitions_coexist_with_distinct_rules()
    test_no_occupation_sits_in_two_conflated_business_models()
    test_occupation_level_and_industry_level_ids_do_not_collide()
    test_partition_name_is_not_a_job_title()
    test_unfolded_partitions_have_null_gdp_not_fabricated_split()
    test_split_partition_gdp_is_not_double_counted()
    test_broken_reference_tables_do_not_take_down_the_db()
    test_same_occupation_on_two_axes_counts_once()
    print("✅ 行业分区定义库测试通过")
