#!/usr/bin/env python3
"""M11 六口径规模账 + 资金流守恒账

盯四件事（都是"钱漏了却没人发现"的几种形态）：

  1. **行业不会因产值缺失整体隐身**：六个口径任一有数就该在表里；
     六格全空的分区必须逐格写清为什么空。
  2. **缺格与悬空必须报**：漏登记一个分区、槽位拼错、资源缺单位，
     都会让某个行业在六口径视角里消失而不报错。
  3. **口径互推只抓数量级错**：利润率/人均产出/PE/PS 超窗口即报 ——
     这类错每个数单看都对，只能靠两个独立来源互推。
  4. **资金流不能凭空生灭**：双边记账是恒等式（不是校验点），真正能抓漏的
     是节点与外部口径对账；没对账口径的节点必须登记未观测流向。
"""
from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

from hanghang.engine.industry_db import IndustryDatabase          # noqa: E402
from hanghang.engine.money_flow import MoneyFlowBook, RECONCILE_TOLERANCE  # noqa: E402
from hanghang.engine.scale_ledger import SCALE_METRICS  # noqa: E402


def _db():
    return IndustryDatabase()


# ------------------------------------------------- 1. 可见度：隐身是不可能的
def test_every_partition_has_a_slot_in_scale_ledger():
    """41 个分区每一个都要在规模账里出现：漏一个就是整体隐身，且不报错"""
    db = _db()
    missing = [p["id"] for p in db.partitions
               if p["id"] not in db.scales.entries]
    assert not missing, f"这 {len(missing)} 个分区在六口径视角里没有任何落点: {missing}"


def test_no_partition_is_fully_hidden():
    """当前数据里不该有全空分区：任一口径有数就能看见，全空必须逐格解释"""
    db = _db()
    hidden = [r["partition"] for r in db.scales.visibility_all()
              if r["level"] == "hidden"]
    assert not hidden, f"这些分区六口径全空（须补数或写 missing 原因）: {hidden}"


def test_visibility_counts_six_metrics():
    """可见度等级按命中口径数判定：>=4 full / 1-3 partial / 0 hidden"""
    db = _db()
    vis = db.scales.visibility("manufacturing")
    assert vis["count"] == len(vis["present"])
    assert vis["count"] + len(vis["missing"]) == len(SCALE_METRICS)
    assert vis["level"] == ("full" if vis["count"] >= 4
                            else "partial" if vis["count"] else "hidden")

    # 行政办公：只有就业口径（企业内部职能，没有独立产值/利润/资产/估值）
    office = db.scales.visibility("admin-office")
    assert office["present"] == ["employment"], office
    assert office["level"] == "partial"
    assert office["missing_detail"]["profit"], "缺格必须带原因，不能只留空"


def test_missing_reason_is_a_sentence_not_empty():
    """缺格的原因要是人话：空串 = 没登记，与"没这个口径"不是一回事"""
    db = _db()
    for row in db.scales.visibility_all():
        for metric, why in row["missing_detail"].items():
            assert why and why != "未填原因", (
                f"{row['partition']} 的 {metric} 缺失但没写原因")


def test_metric_reads_partition_as_single_source():
    """gdp / employment 不重复存：一律从 partition 读，账本里不许有第二份"""
    db = _db()
    p = db.partition("manufacturing")
    gdp = db.scales.metric("manufacturing", "gdp")
    assert gdp["cny"] == p["gdp_cny"]
    assert gdp["kind"] == p["gdp_kind"]
    emp = db.scales.metric("manufacturing", "employment")
    assert emp["wan"] == p["employment"]
    # 账本文件里刻意没有这两个口径的字段（只有 missing 里可能提到）
    raw = db.scales.entries["manufacturing"]
    assert "gdp" not in raw and "employment" not in raw, raw.keys()


# ------------------------------------------------- 2. 悬空与拼错都要报
def test_partition_missing_from_ledger_is_reported():
    """从账本里删掉一个分区 → 第 21 条必须报（否则那个行业悄悄隐身）"""
    db = _db()
    db.scales.entries.pop("logistics-supply", None)
    problems = db.validate()
    assert any("logistics-supply" in p and "industry-scales" in p
               for p in problems), problems


def test_dangling_ledger_entry_is_reported():
    """账本里多出一个不存在的分区 → 悬空记录，永远查不到"""
    db = _db()
    db.scales.entries["no-such-partition"] = {"profit": {"cny": 1.0}}
    assert any("no-such-partition" in p for p in db.validate())


def test_resource_without_unit_is_reported():
    """资源消耗是实物量：没单位数字没有意义"""
    db = _db()
    cell = db.scales.entries["manufacturing"]["resource"]
    cell.pop("unit", None)
    assert any("resource.unit" in p for p in db.validate()), db.validate()


def test_negative_asset_is_reported_but_negative_profit_is_not():
    """资产为负不可能；利润为负是真实存在的（亏损本来就该记）"""
    db = _db()
    entry = db.scales.entries["manufacturing"]
    entry["asset"]["cny"] = -1
    assert any("asset" in p and "为负" in p for p in db.validate())
    entry["asset"]["cny"] = 1.7e15
    entry["profit"]["cny"] = -1e11
    assert not any("profit" in p and "为负" in p for p in db.validate())


def test_unknown_confidence_is_reported():
    db = _db()
    db.scales.entries["manufacturing"]["profit"]["confidence"] = "很高"
    assert any("confidence" in p for p in db.validate())


# ------------------------------------------------- 3. 口径互推只抓数量级错
def test_profit_margin_out_of_window_is_reported():
    """利润填成产值的 3 倍 → 一定是单位错了（或把流水当营业收入）"""
    db = _db()
    db.scales.entries["dongjiagoushi"]["profit"]["cny"] = 1.8e13
    problems = db.scales.cross_check()
    assert any("dongjiagoushi" in p and "profit/gdp" in p for p in problems), problems


def test_per_head_output_catches_1e4_misplacement():
    """人数少填 1e4 倍（单位写成"人"而不是"万人"）→ 人均产出爆表，必须报"""
    db = _db()
    db.partition("manufacturing")["employment"] = 0.8   # 应为 8000 万人
    problems = db.scales.cross_check()
    assert any("manufacturing" in p and "人均产出" in p for p in problems), problems


def test_pe_out_of_window_is_reported():
    """估值与利润差三个数量级 → PE 爆掉，报"""
    db = _db()
    db.scales.entries["e-commerce"]["valuation"]["cny"] = 1.2e20
    problems = db.scales.cross_check()
    assert any("e-commerce" in p and "PE" in p for p in problems), problems


def test_cross_check_is_quiet_on_real_data():
    """真实数据必须干净：宁可漏报，不可误报 —— 误报一次整条校验就会被关掉"""
    db = _db()
    assert db.scales.cross_check() == [], db.scales.cross_check()


def test_hidden_partition_must_explain_every_gap():
    """六口径全空 + 没写原因 → 报。说不出总量又不说什么缺 = 保证会漏"""
    db = _db()
    db.scales.entries["esports"] = {"_missing": {m: "" for m in SCALE_METRICS}}
    problems = db.validate()
    assert any("esports" in p and "没有说明为什么空" in p for p in problems), problems


# ------------------------------------------------- 4. 资金流守恒
def test_double_entry_identity_holds():
    """双边记账下全局流入 ≡ 全局流出。这是恒等式，不是校验成果。"""
    book = _db().money
    total_in = total_out = 0.0
    for f in book.flows:
        amt = f.get("amount_cny")
        if amt is None:
            continue
        total_in += amt
        total_out += amt
    assert total_in == total_out


def test_node_reconciles_against_declared_total():
    """每个声明了对账口径的节点，图上画出来的边必须对得上外部总量"""
    book = _db().money
    rec = book.reconcile()
    bad = [r for r in rec if r["status"] == "gap"]
    assert not bad, f"这些节点对账不上（说明有流向没画）: {bad}"
    # 五个机构部门都要有对账口径
    assert len({r["node"] for r in rec if r["status"] == "ok"}) >= 5


def test_leaking_flow_is_caught_by_reconciliation():
    """删掉一条大额流向 → 该节点对账立刻不平。这是唯一能抓漏的一条。"""
    book = _db().money
    before = len(book.flows)
    book.flows = [f for f in book.flows
                  if not (f.get("from") == "sector-enterprise"
                          and f.get("kind") == "wage")]
    assert len(book.flows) == before - 1
    gaps = [r for r in book.reconcile() if r["status"] == "gap"]
    assert any(r["node"] == "sector-household" and r["side"] == "in"
               for r in gaps), gaps


def test_reconcile_tolerance_is_only_order_of_magnitude():
    """容差是 10%：只抓"漏了一整条流向"，不抓资金流量表的固有口径差"""
    assert RECONCILE_TOLERANCE == 0.10


def test_flow_to_unknown_node_is_reported():
    """钱流向不存在的节点 = 凭空消失，必须报"""
    book = _db().money
    book.flows.append({"from": "sector-enterprise", "to": "pool:no-such",
                       "kind": "allocation", "amount_cny": 1e10})
    assert any("pool:no-such" in p for p in book.validate())


def test_negative_amount_is_reported():
    """方向由 from/to 表达，金额只写正数；负数会让净额算错"""
    book = _db().money
    book.flows.append({"from": "sector-enterprise", "to": "sector-household",
                       "kind": "wage", "amount_cny": -1e10})
    problems = book.validate()
    assert any("为负" in p for p in problems), problems


def test_duplicate_edge_is_reported():
    """同一笔钱记两遍 → 总量直接虚增"""
    book = _db().money
    book.flows.append({"from": "sector-enterprise", "to": "sector-household",
                       "kind": "wage", "amount_cny": 1e10})
    assert any("记了 2 次" in p for p in book.validate())


def test_self_loop_is_reported():
    book = _db().money
    book.flows.append({"from": "sector-household", "to": "sector-household",
                       "kind": "other", "amount_cny": 1e10})
    assert any("自流" in p for p in book.validate())


def test_free_form_flow_kind_is_reported():
    """类型是聚合的唯一维度：随手新增一个词，按类型汇总就多出一行没人认的钱"""
    book = _db().money
    book.flows.append({"from": "sector-enterprise", "to": "sector-household",
                       "kind": "随便一个新类型", "amount_cny": 1e10})
    assert any("kind=" in p for p in book.validate())


def test_node_without_declared_or_unobserved_is_reported():
    """既没对账口径、又不登记未观测 → 保证会漏却静默通过"""
    book = _db().money
    book.unobserved = [u for u in book.unobserved
                       if u.get("node") != "pool:manufacturing"]
    problems = book.validate()
    assert any("pool:manufacturing" in p and "unobserved" in p
               for p in problems), problems


def test_leak_must_have_reason():
    """有差额可以，不解释不行"""
    book = _db().money
    book.leaks.append({"node": "sector-government", "side": "in",
                       "amount_cny": 1e12})
    assert any("没写原因" in p for p in book.validate())


def test_pool_nodes_are_derived_from_pools_section():
    """行业池节点由 pools 段派生，不手写 —— 同一件事存两份迟早对不上"""
    book = _db().money
    ids = {n["id"] for n in book.nodes if n.get("type") == "industry"}
    expected = {f"pool:{row['partition']}" for row in book.pools}
    assert ids == expected, (ids, expected)


def test_null_amount_is_not_zero():
    """amount_cny 为 null 的边仍让图完整，但不能被当成 0 参与净额"""
    book = _db().money
    pos = book.position("pool:manufacturing")
    assert pos["inflow"] == 0.0
    assert pos["unknown_edges"] == 1, pos
    assert pos["net"] == 0.0


# ------------------------------------------------- 5. 汇总与导出
def test_compute_exposes_scale_and_money_summary():
    s = _db().compute()
    assert set(s["scale"]["present_counts"]) == set(SCALE_METRICS)
    assert s["scale"]["level_counts"]["hidden"] == 0
    assert s["money"]["nodes"] >= 5
    assert 0.0 <= s["money"]["amount_coverage"] <= 1.0


def test_scale_metric_table_is_one_row_per_metric():
    """六口径摊成行：缺的口径也占一行，让"隐身"在库里看得见"""
    from hanghang.engine import industry_schema
    rows = industry_schema.rows_of(_db(), _db().compute())
    rows = [r for r in rows["scale_metric"] if r[0] == "admin-office"]
    assert len(rows) == len(SCALE_METRICS)
    # 每一行都在：有数的 value 非空，没数的 missing_reason 非空
    for pid, metric, value, unit, kind, basis, source, conf, reason in rows:
        assert (value is None) != (reason == ""), (metric, value, reason)


def test_empty_ledger_file_is_not_silent_pass():
    """评审二轮：文件在、内容只有注释（空账）时 `exists()` 返回 True，
    于是"每条校验都没有违规"，自检全绿。缺文件和空账必须分开报。"""
    import shutil
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        for name in ("industry-occupations.yaml", "industry-partitions.yaml",
                     "occupation-memberships.yaml"):
            shutil.copy2(os.path.join(ROOT, "data", name),
                         os.path.join(td, name))
        shutil.copytree(os.path.join(ROOT, "data", "reference"),
                        os.path.join(td, "reference"))
        shutil.copy2(os.path.join(ROOT, "data", "industry-scales.yaml"),
                     os.path.join(td, "industry-scales.yaml"))
        with open(os.path.join(td, "industry-money-flows.yaml"), "w",
                  encoding="utf-8") as fh:
            fh.write("version: '0.1'\n# 只有注释\n")
        problems = IndustryDatabase(data_dir=td).validate()
    assert any("空账" in p for p in problems), problems


def test_gap_side_is_normalized_for_export_and_validate():
    """评审二轮：money_gap 主键 (node,kind,side)，leaks 不写 side 时要规范成 n/a，
    导出与校验必须共用同一个口径 —— 否则「没写」和「写了空」永远分不清。"""
    from hanghang.engine import industry_schema
    db = _db()
    # 已有 leaks 里 sector-government/in 已有一条；再记一笔同侧的就是重复
    db.money.leaks.append({"node": "sector-government", "side": "in",
                           "amount_cny": 1e11, "reason": "第二笔"})
    assert any("sector-government" in p and "登记了 2 次" in p
               for p in db.money.validate())
    # 删掉重复项后必须能干净落库（反证：不是靠报错掩盖主键冲突）
    db.money.leaks.pop()
    rows = industry_schema.rows_of(db, db.compute())["money_gap"]
    keys = [(r[0], r[1], r[2]) for r in rows]
    assert len(keys) == len(set(keys)), keys
    assert all(r[2] for r in rows if r[1] == "gap"), "gap 行的 side 不许为空"


def test_loaded_flag_is_exposed():
    """读 summary 的人不该看到一张"干净且空"的账"""
    db = _db()
    assert db.money.coverage_summary()["loaded"] is True


def test_money_table_columns_are_aligned():
    """评审 4-补充：CJK 按字符数补空格会把后几列顶歪（'待补边' 3 字 6 列，给 5 列就超）"""
    import unicodedata

    def width(t):
        return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1
                   for c in t)

    lines = _db().money.render_text().splitlines()
    head = next(i for i, ln in enumerate(lines) if "流入(亿)" in ln)
    rows = [ln for ln in lines[head:head + 6] if ln.startswith(("居民", "非金融"))]
    assert rows
    for ln in rows:
        assert width(ln) == width(lines[head]), (
            f"列宽错位: {width(ln)} vs {width(lines[head])}\n{ln}")


def test_export_includes_ledgers():
    """导出必须带两本账：缺口本身就是要交付的信息"""
    import json
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        subprocess.run([sys.executable,
                        os.path.join(ROOT, "src/hanghang/cli/main.py"),
                        "industry", "export", "--out", td],
                       check=True, capture_output=True, cwd=ROOT)
        data = json.load(open(os.path.join(td, "industry-db.json"),
                              encoding="utf-8"))
        assert len(data["scales"]) == len(_db().partitions)
        assert data["money"]["summary"]["nodes"] >= 5
        for name in ("scales.csv", "money-nodes.csv", "money-flows.csv"):
            assert os.path.getsize(os.path.join(td, name)) > 0, name


# ------------------------------------------------- 评审回归（PR #34）
def test_wrong_amount_key_does_not_crash_cross_check():
    """评审 1：profit 写成 {wan: ...} 时 cross_check 曾 KeyError → industry check traceback。

    校验器自己挂了是最难查的故障：红灯既不是"数据坏了"也不是"绿"。
    现在按口径只认它自己那一个键，写错键单独报出来（键写错会让这一格静默变空，
    而「没统计到」与「写错了」不是一回事）。
    """
    db = _db()
    db.scales.entries["manufacturing"]["profit"] = {"wan": 9e6}
    assert db.scales.cross_check() == []          # 不崩
    problems = db.validate()
    assert any("manufacturing" in p and "'wan'" in p for p in problems), problems


def test_wrong_amount_key_on_other_metrics():
    """asset / valuation / resource 写错键同样要报，不只是 profit"""
    # asset/valuation 认 cny，resource 认 value —— 各自写成别的口径的键都要报
    for name, wrong in (("asset", "wan"), ("valuation", "wan"),
                        ("resource", "cny")):
        db = _db()
        db.scales.entries["manufacturing"][name] = {wrong: 1e9}
        assert any(name in p and wrong in p for p in db.validate()), (name, wrong)


def test_missing_key_typo_is_reported():
    """评审 7：missing 的键拼错（assett）→ 该格显示"未填原因"而 validate 不报，
    正是"说不出总量又不说什么缺"这条最该守住的东西被绕过。"""
    db = _db()
    db.scales.entries["manufacturing"]["_missing"]["assett"] = "拼错了"
    assert any("assett" in p for p in db.validate())


def test_loss_making_industry_does_not_trigger_pe_alarm():
    """评审 8：亏损行业（利润 < 0）的 PE 是负倍数，不该被当成"倍数爆表"误报"""
    db = _db()
    entry = db.scales.entries["manufacturing"]
    entry["profit"]["cny"] = -1e10          # 亏损
    entry["valuation"] = {"cny": 1.2e12}
    assert db.scales.cross_check() == [], db.scales.cross_check()


def test_duplicate_gap_registration_is_reported():
    """评审 4：money_gap 主键 (node, kind, side)，重复登记时 validate 曾返回 []
    而导库撞 UNIQUE。同一笔钱记两遍在 flow 上拦了，gap 上不能漏。"""
    db = _db()
    db.money.unobserved.append({"node": "pool:manufacturing",
                               "missing": "第二条第", "reason": "重复登记"})
    assert any("pool:manufacturing" in p and "登记了 2 次" in p
               for p in db.money.validate())


def test_pools_exists_even_when_file_missing():
    """评审 5：资金流文件缺失时 pools 未初始化 → 降级路径比错误数据更脆"""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        book = MoneyFlowBook(data_dir=td)
        assert book.pools == []
        assert book.validate(), "空账必须报出来"


def test_money_columns_are_bigint_in_postgresql():
    """评审 2：gdp_cny 最大 33 万亿，而 PG 的 INTEGER 上限 21 亿 →
    "拿到 SQL 直接跑"会在第一条 partition 就 numeric field overflow。
    SQLite 不做类型强校验，所以导入往返自检全绿，这个错只有真进 PG 才露。
    """
    from hanghang.engine import industry_schema as sch
    pg = sch.ddl("postgresql")
    for table in ("partition", "money_node", "money_flow", "money_gap"):
        cols = [c for c in pg.split(f'CREATE TABLE IF NOT EXISTS "{table}"')[1]
                .split(");")[0].splitlines()]
        for line in cols:
            name = line.strip().split('"')[1] if '"' in line else ""
            if name.endswith("_cny"):
                assert "BIGINT" in line, f"{table}.{name} 不是 BIGINT: {line}"
                assert " INTEGER" not in line, f"{table}.{name} 仍是 INTEGER"


def test_not_null_is_actually_rendered():
    """评审 6：_col_sql 两个分支都返回空串，生成的 DDL 里 NOT NULL 计数为 0。
    后果不是报错而是契约不成立：money_gap.reason 可为 NULL，而 validate 要求
    "有差额不解释不行"。"""
    from hanghang.engine import industry_schema as sch
    for dialect in ("sqlite", "postgresql"):
        ddl = sch.ddl(dialect)
        assert "NOT NULL" in ddl, dialect
    # 主键列必须 NOT NULL（SQLite 的非整数主键不拒绝 NULL，靠这行兜住）
    pg = sch.ddl("postgresql")
    for name in ("money_gap", "scale_metric"):
        body = pg.split(f'CREATE TABLE IF NOT EXISTS "{name}"')[1].split(");")[0]
        assert '"node" TEXT NOT NULL' in body or '"partition" TEXT NOT NULL' in body


def test_missing_data_files_never_self_check_pass():
    """两本账的数据文件缺失时必须报出来。

    这是本仓库第 13 条防的那类故障：0 个节点、0 条边，"每条校验都没有违规"，
    于是自检全绿 —— 而它其实一张空账。空账不可能守恒任何东西。
    """
    import shutil
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        for name in os.listdir(os.path.join(ROOT, "data")):
            src = os.path.join(ROOT, "data", name)
            dst = os.path.join(td, name)
            if os.path.isdir(src):
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
        for name in ("industry-scales.yaml", "industry-money-flows.yaml"):
            os.remove(os.path.join(td, name))
        problems = IndustryDatabase(data_dir=td).validate()
    assert any("未读到六口径规模账" in p for p in problems), problems
    assert any("未读到资金流守恒账" in p for p in problems), problems


def test_cli_scale_and_money_run():
    """CLI 两条命令能跑出人话（不是 traceback）"""
    for argv, needle in ((["industry", "scale", "--gaps"], "六口径"),
                         (["industry", "scale", "--partition", "manufacturing"],
                          "年产值"),
                         (["industry", "money", "--node", "sector-household"],
                          "对账")):
        out = subprocess.run(
            [sys.executable, os.path.join(ROOT, "src/hanghang/cli/main.py")] + argv,
            capture_output=True, text=True, cwd=ROOT)
        assert out.returncode == 0, out.stderr
        assert needle in out.stdout, out.stdout


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ✅ {name}")
    print("✅ 六口径规模账 + 资金流守恒账测试通过")
