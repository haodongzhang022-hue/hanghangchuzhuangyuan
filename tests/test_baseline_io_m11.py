#!/usr/bin/env python3
"""M11 官方口径基准（逐年对表）+ 投入产出账（生产法去重）

盯四件事，都是"数字看着有出处、其实没人验过"或"数字都对、加起来才不对"的形态：

  1. `gdp_confidence=high` 必须是**可核对**的，不能是自我声明：有 high 就必须有
     同口径、同年份、偏差在容差内的对表记录。
  2. 每个有产值的分区都要"有对表"或"写清为什么没有可比口径" —— 说不出为什么，
     等于这个数永远不会被验，而没人知道。
  3. 生产法恒等式 `总产出 = 增加值 + 中间投入` 三端对不上要报；缺的一端必须写
     原因。三处重复计（构成合计≠总额、供给超过自身产出、增加值合计>GDP）要拦住。
  4. 行业池切分只认**增加值口径锚点**：GMV/成本总额/营业收入一律不可切，因为
     部门层总额是增加值性质，拿收入切出来的份额必然虚高且看不出来。
  5. `allocation` 是备忘边：计入节点头寸会让部门凭空多出一笔钱。
"""
from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

from hanghang.engine.industry_db import IndustryDatabase            # noqa: E402
from hanghang.engine.input_output import InputOutputBook            # noqa: E402
from hanghang.engine.money_flow import MoneyFlowBook                # noqa: E402
from hanghang.engine.official_baseline import OfficialBaseline      # noqa: E402


def _db():
    return IndustryDatabase()


# ------------------------------------------------- 1. 对表：high 不能自己写
def test_high_confidence_needs_passing_link():
    """标了 high 的分区必须有通过的对表：否则 high 只是一句自我声明"""
    db = _db()
    problems = db.baseline.validate()
    assert not [p for p in problems if "high" in p], problems
    for p in db.partitions:
        if p.get("gdp_confidence") != "high" or not p.get("gdp_cny"):
            continue
        r = next(x for x in db.baseline.compare() if x["partition"] == p["id"])
        assert r["status"] == "ok", (p["id"], r)


def test_high_without_link_is_reported():
    """把一个没接基准的分区标成 high，必须报出来"""
    db = _db()
    p = db.partition("game-dev-unit")
    p["gdp_confidence"] = "high"
    problems = db.validate()
    p["gdp_confidence"] = "medium"
    assert any("game-dev-unit" in x and "high" in x for x in problems), problems


def test_every_valued_partition_is_linked_or_explained():
    """有产值就必须有对表或没可比口径的说明：一张都不能少"""
    db = _db()
    for p in db.partitions:
        if not p.get("gdp_cny"):
            continue
        linked = db.baseline.link_of(p["id"])
        why = db.baseline.unlinked_reason(p["id"])
        assert linked or why, f"{p['id']} 有产值但既没对表也没说明"


def test_unexplained_partition_is_reported():
    """把某个分区从 unlinked 分组里摘掉 → 必须报「既没接也没说明」"""
    db = _db()
    target = "data-analytics"
    saved = db.baseline.unlinked
    db.baseline.unlinked = [g for g in saved
                            if target not in (g.get("partitions") or [])]
    problems = db.baseline.validate()
    db.baseline.unlinked = saved
    assert any(target in x and "可比口径" in x for x in problems), problems


def test_gap_is_reported_with_numbers():
    """产值与官方偏差超容差必须报，且报出两个数与偏差"""
    db = _db()
    p = db.partition("manufacturing")
    saved = p["gdp_cny"]
    p["gdp_cny"] = 50000000000000        # 50 万亿 vs 33 万亿
    problems = db.baseline.validate()
    p["gdp_cny"] = saved
    hit = [x for x in problems if "manufacturing" in x and "容差" in x]
    assert hit, problems


def test_incomparable_requires_reason():
    """声明 incomparable 却不写 reason → 报错（口径不同必须说清哪里不同）"""
    db = _db()
    lk = db.baseline.link_of("dongjiagoushi")
    saved = lk.pop("reason")
    problems = db.baseline.validate()
    lk["reason"] = saved
    assert any("incomparable" in x and "reason" in x for x in problems), problems


def test_series_year_must_be_known():
    """基准 series 出现不在全局 years 里的年份 → 报错（同比与对齐都会算错）"""
    db = _db()
    bench = db.baseline.benchmark("revenue-catering")
    bench["series"].append({"year": 2019, "value_cny": 4e12,
                            "source": "test", "confidence": "low"})
    problems = db.baseline.validate()
    bench["series"].pop()
    assert any("不在全局 years" in x for x in problems), problems


def test_year_falls_back_to_basis_range_not_hardcoded():
    """分区没写 gdp_year 时，年份从区间里取**基准已有**的末年，不硬取 2024

    硬取会让"官方没这一年的数"看起来像"对不上" —— 其实只是基准还没录。
    """
    db = _db()
    p = db.partition("manufacturing")
    p.pop("gdp_year", None)
    p["gdp_year_basis"] = "2023-2024"
    year, src = db.baseline.part_year(p)
    assert year == 2023 and src == "basis_range", (year, src)
    p["gdp_year"] = 2022
    assert db.baseline.part_year(p) == (2022, "declared")


def test_yoy_needs_two_years():
    """同比只在两年以上 series 上给；单年基准不许凑一个增速出来"""
    db = _db()
    sports = db.baseline.benchmark("sports-output")
    assert len(sports["series"]) == 1
    assert db.baseline.yoy("sports-output") is None
    assert db.baseline.yoy("revenue-catering") is not None


def test_confidence_of_is_derived_not_declared():
    """机器判定的置信度：对上=high，不可比≤medium，没接=low"""
    db = _db()
    assert db.baseline.confidence_of("manufacturing") == "high"
    assert db.baseline.confidence_of("dongjiagoushi") in ("medium", "low")
    assert db.baseline.confidence_of("game-dev-unit") == "low"


# ------------------------------------------------- 2. 生产法三端
def test_production_identity_closes_for_construction():
    """建筑业是本轮的样板：31.6 = 8.6 + 23.0，三端全有官方出处"""
    db = _db()
    r = db.input_output.identity("construction-eng")
    assert r["status"] == "ok", r
    assert r["derived"] is True
    assert abs(r["output"] - (r["value_added"] + r["intermediate"])) < 1
    assert 0.2 < r["va_ratio"] < 0.35


def test_gap_in_identity_is_reported():
    """三端都在但对不上 → 报「三边不同源，必有一个是别的口径」"""
    db = _db()
    acc = db.input_output.accounts["construction-eng"]
    saved = acc["intermediate"]["cny"]
    acc["intermediate"]["cny"] = 5000000000000      # 5 万亿，对不上
    problems = db.input_output.validate()
    acc["intermediate"]["cny"] = saved
    assert any("生产法对不上" in x for x in problems), problems


def test_partial_identity_requires_reason():
    """缺一端必须写清为什么：说不出，等于保证它永远对不上"""
    db = _db()
    acc = db.input_output.accounts["e-commerce"]
    saved = acc["missing"].pop("value_added")
    problems = db.input_output.validate()
    acc["missing"]["value_added"] = saved
    assert any("e-commerce" in x and "没写原因" in x for x in problems), problems


def test_valued_partition_needs_io_slot():
    """有产值的分区必须有生产法落点，漏一个就是"这个数切分时必然重复计" """
    db = _db()
    for p in db.partitions:
        if p.get("gdp_cny"):
            assert p["id"] in db.input_output.accounts, p["id"]


def test_inputs_sum_must_match_total_when_complete():
    """声明 complete 时，中间投入构成合计必须等于总额"""
    db = _db()
    acc = db.input_output.accounts["construction-eng"]
    acc["intermediate"]["cny"] = 23000000000000
    acc["inputs"] = [{"from": "manufacturing", "cny": 10000000000000}]
    acc["complete"] = True
    problems = db.input_output.validate()
    acc.pop("inputs")
    acc.pop("complete")
    assert any("中间投入构成合计" in x for x in problems), problems


def test_supply_cannot_exceed_own_output():
    """某分区作为投入方供给的合计不能超过它自己的总产出（去重的关门条件）"""
    db = _db()
    acc = db.input_output.accounts["construction-eng"]
    acc["inputs"] = [{"from": "e-commerce", "cny": 20000000000000}]
    problems = db.input_output.validate()
    acc.pop("inputs")
    assert any("超过它自己的总产出" in x for x in problems), problems


def test_va_total_cannot_exceed_gdp():
    """所有分区增加值合计不能超过全国 GDP：超了是同一笔价值算了两遍"""
    db = _db()
    acc = db.input_output.accounts["manufacturing"]
    saved = acc["value_added"]["cny"]
    acc["value_added"]["cny"] = 130000000000000    # 130 万亿 > GDP
    problems = db.input_output.validate()
    acc["value_added"]["cny"] = saved
    assert any("超过全国 GDP" in x for x in problems), problems


def test_va_ratio_out_of_range_is_reported():
    """增加值率必须在 (0,1)：超过 1 说明拿总产值当分子了"""
    db = _db()
    acc = db.input_output.accounts["construction-eng"]
    saved = acc["va_ratio"]
    acc["va_ratio"] = 1.4
    problems = db.input_output.validate()
    acc["va_ratio"] = saved
    assert any("va_ratio" in x for x in problems), problems


def test_va_ratio_never_backfilled_by_average():
    """缺一端时不许用行业平均值凑一个增加值率：那是看起来合理的错数"""
    db = _db()
    assert db.input_output.va_ratio("e-commerce") is None
    assert db.input_output.va_ratio("manufacturing") is None


# ------------------------------------------------- 3. 切分只能锚增加值
def test_only_value_added_anchors_are_ready():
    """可切的池必须有增加值口径锚点；GMV/成本总额/营业收入一律不可切"""
    db = _db()
    rows = {r["partition"]: r for r in db.input_output.pool_feasibility()}
    for pid in ("e-commerce", "logistics-supply", "dongjiagoushi"):
        assert rows[pid]["status"] == "blocked", (pid, rows[pid])
        assert rows[pid]["anchor_value"] is None
    for pid in ("manufacturing", "construction-eng"):
        assert rows[pid]["status"] == "ready", (pid, rows[pid])
        assert rows[pid]["anchor_value"]


def test_allocation_rows_never_fill_without_anchor():
    """没锚点的池金额必须是 None，不许摊一个数出来"""
    db = _db()
    anchors = {r["partition"]: r["anchor_value"]
               for r in db.input_output.pool_feasibility()
               if r["status"] == "ready" and r["anchor_value"]}
    rows = {r["partition"]: r for r in db.money.allocation_rows(anchors)}
    assert rows["manufacturing"]["filled"] is True
    assert rows["e-commerce"]["filled"] is False
    assert rows["e-commerce"]["amount_cny"] is None


def test_unknown_anchor_is_not_a_valid_anchor():
    """锚点枚举写错 → 报错（写错会让不可切的池看起来可切）"""
    db = _db()
    rule = db.input_output.pool_rules[0]
    saved = rule["anchor"]
    rule["anchor"] = "revenue"
    problems = db.input_output.validate()
    rule["anchor"] = saved
    assert any("anchor" in x for x in problems), problems


# ------------------------------------------------- 4. memo：摊开看 ≠ 新钱
def test_allocation_is_memo_and_excluded_from_position():
    """allocation 必须标 memo，且不计入节点头寸：否则部门凭空多出一笔钱"""
    db = _db()
    memo = [f for f in db.money.flows if f.get("kind") == "allocation"]
    assert memo, "本账应有 allocation 备忘边"
    assert all(f.get("memo") is True for f in memo)
    pos = db.money.position("sector-enterprise")
    assert pos["memo_edges"] == len(memo)
    # 流出只算真实边：wage 64 + tax 19.7 + interest 6 + saving 2.4 + import 18
    assert abs(pos["outflow"] - 110100000000000) < 1e9, pos


def test_memo_flag_mismatch_is_reported():
    """memo 与 kind 不一致要报：标错会静默漏掉一笔真钱，或凭空多出一笔"""
    db = _db()
    f = next(x for x in db.money.flows if x.get("kind") == "wage")
    f["memo"] = True
    problems = db.money.validate()
    f["memo"] = False
    assert any("memo" in x for x in problems), problems


def test_allocation_without_memo_is_reported():
    """allocation 不标 memo → 报错（计入头寸会让部门双计）"""
    db = _db()
    f = next(x for x in db.money.flows if x.get("kind") == "allocation")
    f.pop("memo")
    problems = db.money.validate()
    f["memo"] = True
    assert any("必须标 memo" in x for x in problems), problems


def test_amount_coverage_excludes_memo():
    """图完整度分母只算真实流：备忘边本来就没数额，算进去会让这个数永远上不去"""
    db = _db()
    t = db.money.totals()
    s = db.money.coverage_summary()
    assert t["memo_flows"] > 0
    assert s["amount_coverage"] == 1.0
    assert s["memo_coverage"] == 0.0


def test_empty_ledger_is_not_a_pass():
    """文件在、内容是注释 → 空账必须硬报，不能「每条校验都通过」"""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        for name in ("industry-official-baseline.yaml",
                     "industry-input-output.yaml"):
            open(os.path.join(td, name), "w", encoding="utf-8").write(
                "# 只有注释\nversion: '0.1'\n")
        base = OfficialBaseline(data_dir=td, partitions=_db().partitions)
        io = InputOutputBook(data_dir=td, partitions=_db().partitions)
        assert any("空账" in x for x in base.validate()), base.validate()
        assert any("空账" in x for x in io.validate()), io.validate()


def test_missing_files_are_reported():
    """文件缺失也不能静默通过"""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        base = OfficialBaseline(data_dir=td, partitions=[])
        io = InputOutputBook(data_dir=td, partitions=[])
        assert any("未读到" in x for x in base.validate())
        assert any("未读到" in x for x in io.validate())


# ------------------------------------------------- 5. 落库与 CLI
def test_schema_version_bumped_and_tables_present():
    """结构单源：新三张表 + money_flow.memo 必须在同一处定义"""
    from hanghang.engine import industry_schema
    names = industry_schema.tables()
    for t in ("baseline_series", "baseline_link", "io_account"):
        assert t in names, names
    assert "memo" in industry_schema.columns_of("money_flow")
    assert industry_schema.SCHEMA_VERSION == "1.3.0"


def test_rows_are_written_not_empty():
    """三张新表都要有行：空表等于「导进去了但什么都没有」"""
    from hanghang.engine import industry_schema
    db = _db()
    c = industry_schema.counts(db, db.compute())
    assert c["baseline_series"] > 0 and c["baseline_link"] == len(db.partitions)
    assert c["io_account"] == len(db.partitions)


def test_cli_baseline_runs():
    out = subprocess.run(
        [sys.executable, os.path.join(ROOT, "src/hanghang/cli/main.py"),
         "industry", "baseline", "--top", "3"],
        capture_output=True, text=True, cwd=ROOT)
    assert out.returncode == 0, out.stderr
    assert "逐年对表" in out.stdout and "high" in out.stdout


def test_cli_io_pools_runs():
    out = subprocess.run(
        [sys.executable, os.path.join(ROOT, "src/hanghang/cli/main.py"),
         "industry", "io", "--pools"],
        capture_output=True, text=True, cwd=ROOT)
    assert out.returncode == 0, out.stderr
    assert "可切" in out.stdout and "不可切" in out.stdout


def test_validate_check_count_is_25():
    """条数仍是一处来源：常量说 25，docstring 编号必须 1..25 连续"""
    import inspect
    import re
    src = inspect.getsource(IndustryDatabase.validate)
    nums = [int(x) for x in re.findall(r"^        (\d+)\. ", src, re.M)]
    assert nums == list(range(1, IndustryDatabase.VALIDATE_CHECK_COUNT + 1)), nums
    assert IndustryDatabase.VALIDATE_CHECK_COUNT == 25


# ------------------------------------------------- 6. 数据盘存清单
def test_inventory_is_not_stale():
    """清单与数据不许分叉：改了数据忘了重生成，清单会指向已不存在的文件"""
    out = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts/gen_data_inventory.py"),
         "--check"], capture_output=True, text=True, cwd=ROOT)
    assert out.returncode == 0, out.stdout + out.stderr


def test_inventory_lists_every_source():
    """每份权威源都要在清单里：漏一份就等于「这份数据没人知道它在哪」"""
    import re
    doc = open(os.path.join(ROOT, "docs/industry/data-inventory.md"),
               encoding="utf-8").read()
    for path in ("industry-occupations.yaml", "industry-partitions.yaml",
                 "industry-scales.yaml", "industry-money-flows.yaml",
                 "industry-official-baseline.yaml", "industry-input-output.yaml"):
        assert path in doc, path
    # 四本账各自守什么也要在清单里，否则清单只是一张文件列表
    for word in ("六口径", "资金流", "官方口径基准", "投入产出"):
        assert word in doc, word
    # 平台路径：知识库/导出/库三个落点都要写
    for word in ("知识库", "out/industry-db", "data/db/industry"):
        assert word in doc, word
    assert re.search(r"\| `scale_metric` \| \d+ \|", doc)


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ✅ {name}")
    print("✅ 官方基准对表 + 投入产出生产法测试通过")
