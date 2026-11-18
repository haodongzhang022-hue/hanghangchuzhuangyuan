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
from hanghang.engine.scale_ledger import SCALE_METRICS          # noqa: E402
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
    """当前数据里不该有**无解释**的全空分区

    scale_ledger.py 对 hidden 的定义是「0 个口径有数，**必须显式说明为什么**」。
    所以这里要卡的是「全空且说不清」，不是「全空」本身：
    一个全新补进来的分区（如零售贸易/交通基建）在拿到独立官方口径之前，
    六格全空但每格都写了原因，是诚实状态，不该被当成"隐身"报错。

    判据：六个口径全空 **且** 六格 missing 原因都写了 → 可接受；
    全空但有一格没写原因 → 报错。
    """
    db = _db()
    bad = []
    for r in db.scales.visibility_all():
        if r["level"] != "hidden":
            continue
        unexplained = [m for m in SCALE_METRICS
                       if not (r["missing_detail"].get(m)
                               and r["missing_detail"][m] != "未填原因")]
        if unexplained:
            bad.append(f"{r['partition']}({unexplained})")
    assert not bad, f"这些分区六口径全空且没写原因（须补数或逐格写 missing）: {bad}"


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
    """amount_cny 为 null 的边仍让图完整，但不能被当成 0 参与净额。

    行业池那条 `allocation` 现在是备忘边（memo）：它把部门总额摊开看，
    不是新发生的一笔钱，所以既不进流入也不进"待补边"—— 但它照样挂在图上，
    `memo_edges` 记着它存在。真正的"待补数额"要看非 memo 边。
    """
    book = _db().money
    pos = book.position("pool:manufacturing")
    assert pos["inflow"] == 0.0
    assert pos["net"] == 0.0
    # 摊开看的边要能被看见，但不能混进"待补数额"
    assert pos["memo_edges"] >= 1, pos
    assert all(f.get("memo") for f in book.flows_of("pool:manufacturing"))


def test_null_real_flow_counts_as_unknown_not_zero():
    """非 memo 边的 null 必须计进待补，且不许当 0 参与净额"""
    book = _db().money
    node = "sector-household"
    before = book.position(node)
    book.flows.append({"from": node, "to": "sector-government",
                       "kind": "tax", "amount_cny": None})
    after = book.position(node)
    book.flows.pop()
    assert after["unknown_edges"] == before["unknown_edges"] + 1, after
    assert after["outflow"] == before["outflow"], after


# ------------------------------------------------- 5. 汇总与导出
def test_compute_exposes_scale_and_money_summary():
    s = _db().compute()
    assert set(s["scale"]["present_counts"]) == set(SCALE_METRICS)
    # hidden 不一定是 0：新补进来的分区在拿到独立官方口径前六格全空是诚实状态。
    # 要卡的是「全空且说不清」——hidden 里的每个分区都必须逐格写了原因。
    db = _db()
    for pid in s["scale"]["hidden"]:
        vis = db.scales.visibility(pid)
        unexplained = [m for m in SCALE_METRICS
                       if not (vis["missing_detail"].get(m)
                               and vis["missing_detail"][m] != "未填原因")]
        assert not unexplained, f"{pid} 六口径全空且未解释: {unexplained}"
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


def test_default_data_dir_points_to_repo_data():
    """评审四轮 P0：默认 data_dir 少一级（../../data 只到 src/data）。

    不带参数构造必然读到空账，而空账在 CLI/Web 上表现为"六个口径全空 /
    零个资金流节点"——看起来像数据没补，实际是路径错了。
    """
    from hanghang.engine.money_flow import MoneyFlowBook
    from hanghang.engine.scale_ledger import ScaleLedger
    sl, book = ScaleLedger(), MoneyFlowBook()
    assert os.path.exists(sl.path), sl.path
    assert os.path.exists(book.path), book.path
    assert sl.path.endswith(os.path.join("data", "industry-scales.yaml"))
    assert sl.entries, "默认构造读到 0 条 = 路径错了"
    assert book.nodes, "默认构造读到 0 个节点 = 路径错了"


def test_render_path_uses_same_num_rule_as_validate():
    """评审四轮：render_text / `--node` 仍用裸值除法，带引号金额直接 traceback。

    「修好了金额」只修好了其中一条路 —— 渲染和校验必须是同一套取值规则。
    """
    db = _db()
    db.money.flows[0]["amount_cny"] = "64e12"
    db.money.leaks[0]["amount_cny"] = "8.6e12"
    db.money.render_text()                              # 不许抛
    assert db.money.position("sector-household")        # 不许抛
    assert any("不是数值" in p for p in db.money.validate())


def test_non_numeric_declared_is_reported_not_downgraded():
    """评审四轮：declared_in_cny 非数值时被降级成 no_declared，validate 不报。

    这等于把**唯一能抓漏的那条**对账静默关掉 —— 比报错更坏。
    """
    db = _db()
    db.money.node("sector-household")["declared_in_cny"] = "80800000000000"
    row = next(r for r in db.money.reconcile()
               if r["node"] == "sector-household" and r["side"] == "in")
    assert row["status"] == "invalid_declared", row
    assert any("declared_in_cny" in p and "不是数值" in p
               for p in db.money.validate())


def test_dirty_gdp_never_crashes_compute_or_render():
    """compute() 里 `sum(p["gdp_cny"])` 遇到字符串会 TypeError，而 compute()
    被 render_text / Web / 导出共用，一处崩三处一起挂。"""
    import hanghang.cli.industry_commands as ic
    db = _db()
    db.partition("manufacturing")["gdp_cny"] = "不是数字"
    db.partition("logistics-supply")["employment"] = "5000"
    s = db.compute()                                    # 不许抛
    db.render_text(top=3)                               # 不许抛
    assert any("gdp_cny" in p and "不是数值" in p for p in db.validate())
    assert any("logistics-supply" in p and "employment" in p
               for p in db.validate()), db.validate()[:5]


def test_non_numeric_gdp_never_crashes_readers():
    """partition.gdp_cny 是字符串时，metric()/cross_check()/CLI 都不许抛。

    partition 上的字段名（gdp_cny/employment）与账本键名（cny/wan）不同，
    早先直接 float() 转换 → ValueError 一路冒到 CLI。数据问题该由 validate 报。
    """
    db = _db()
    db.partition("manufacturing")["gdp_cny"] = "不是数字"
    assert db.scales.metric("manufacturing", "gdp") is None       # 不许抛
    assert db.scales.cross_check() == []                          # 不许抛
    db.scales.visibility("manufacturing")                         # 不许抛
    assert any("gdp_cny" in p and "不是数值" in p for p in db.validate())


def test_partition_side_keys_are_mapped_explicitly():
    """gdp→gdp_cny / employment→employment 必须显式映射，不靠"试着取一遍"。"""
    from hanghang.engine.scale_ledger import ScaleLedger
    assert ScaleLedger.PARTITION_KEY == {"gdp": "gdp_cny",
                                         "employment": "employment"}
    db = _db()
    assert db.scales.metric("manufacturing", "gdp")["cny"] == 33e12
    assert db.scales.metric("manufacturing", "employment")["wan"] == 8000


def test_non_numeric_amount_never_crashes_position_or_totals():
    """评审三轮：amount_cny 写成带引号的 "64e12" 时，position()/totals() 在 += 上
    TypeError —— 而这两个是 CLI 与导出都要走的路。

    数字不对是数据问题，不该变成崩溃；该报的是 validate()。
    """
    db = _db()
    db.money.flows.append({"from": "sector-enterprise", "to": "sector-household",
                           "kind": "other", "amount_cny": "64e12"})
    pos = db.money.position("sector-household")       # 不许抛
    assert pos["unknown_edges"] == 1
    assert db.money.totals()["flows_without_amount"] >= 1   # 不许抛
    assert any("不是数值" in p for p in db.money.validate())
    # 声明口径也可能是字符串同理
    db.money.node("sector-household")["declared_in_cny"] = "80800000000000"
    db.money.reconcile()                               # 不许抛


def test_gap_side_export_and_validate_share_one_rule():
    """评审三轮：导出侧用原始 side、校验侧用 gap_side() → 两套主键。

    校验认 n/a、导出写空串，导库时照样撞 UNIQUE —— "修复"本身成了漏洞。
    两边必须调同一个函数。
    """
    from hanghang.engine import industry_schema
    db = _db()
    db.money.leaks.append({"node": "sector-government", "amount_cny": 1e11,
                           "reason": "不写 side 的一笔"})
    keys_check = {(lk.get("node"), db.money.gap_side(lk, "gap"))
                  for lk in db.money.leaks}
    rows = [r for r in industry_schema.rows_of(db, db.compute())["money_gap"]
            if r[1] == "gap"]
    keys_export = {(r[0], r[2]) for r in rows}
    assert keys_export == keys_check, (keys_export, keys_check)
    assert ("sector-government", "n/a") in keys_export, keys_export


def test_scale_cli_survives_dirty_metric_value():
    """评审三轮：`scale --partition` 把 None 送进 f-string 的 ":,.0f" 会 TypeError。

    只读命令不该让看数据的人拿到 traceback——一份脏数据不等于一次崩溃。
    """
    import subprocess
    import textwrap
    code = textwrap.dedent("""
        import sys
        sys.path.insert(0, "src")
        import hanghang.engine.scale_ledger as sl
        orig = sl.ScaleLedger.metric
        def fake(self, pid, name):
            r = orig(self, pid, name)
            if r and name == "employment":
                r.pop("wan", None)      # 模拟槽位里只剩来源、没有数值
            return r
        sl.ScaleLedger.metric = fake
        from hanghang.cli.industry_commands import cmd_industry_scale
        class A:
            partition = "manufacturing"; top = 0; only = ""; gaps = False
            data_dir = ""
        cmd_industry_scale(A)
    """)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, cwd=ROOT)
    assert "Traceback" not in out.stderr, out.stderr
    assert out.returncode == 0, out.stderr
    assert "从业人数" in out.stdout


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


# ------------------------------------- 评审六轮：结构写歪（不是"非数值"，是"形状错"）
def _tmp_data(*overrides):
    """复制一份 data/ 到临时目录，按 (文件名, 改法) 覆盖。

    为什么必须落到临时目录而不是 patch 内存对象：这几条要验的是
    "`_load()` 能不能把写歪的 yaml 变成一句人话"。绕过 yaml 直接改对象，
    验的是我写的兜底代码，不是真实入口。
    """
    import shutil
    import tempfile
    import yaml

    td = tempfile.mkdtemp()
    for name in os.listdir(os.path.join(ROOT, "data")):
        src = os.path.join(ROOT, "data", name)
        dst = os.path.join(td, name)
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
    for name, mutate in overrides:
        path = os.path.join(td, name)
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        mutate(data)
        with open(path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, allow_unicode=True)
    return td


def test_any_list_section_with_a_stray_string_is_reported_not_raised():
    """结构写歪：列表里混一个字符串，五本账都不许崩，且都要报成人话

    评审六轮第 1 条。`(it or {})` 只兜得住 None，兜不住字符串 ——
    而数据是人或模型手写的，列表里混一个字符串是最常见的写法之一。
    于是 `industry check` 这个 CI 闸自己 traceback：红灯既不是"数据坏了"，
    也不是"绿"。

    修法不是在每个消费点再兜一次（想到的路之外的路照样炸），而是
    **在 `_load()` 入口统一归一段形状**，写歪的项记一条 problem 交给 validate。
    """
    from hanghang.engine.input_output import InputOutputBook
    from hanghang.engine.official_baseline import OfficialBaseline
    from hanghang.engine.strategy_view import StrategyView

    cases = [
        ("industry-strategy.yaml",
         lambda d: d["partitions"][0]["profit_pool"].append("一个字符串"),
         StrategyView, "利润池"),
        ("industry-scales.yaml",
         lambda d: d["scales"].append("坏行"),
         None, "scales"),
        ("industry-money-flows.yaml",
         lambda d: d["pools"].append("坏"),
         MoneyFlowBook, "pools"),
        ("industry-input-output.yaml",
         lambda d: d["accounts"].append("坏"),
         InputOutputBook, "accounts"),
        ("industry-official-baseline.yaml",
         lambda d: d["benchmarks"].append("坏"),
         OfficialBaseline, "benchmarks"),
    ]
    for name, mutate, cls, needle in cases:
        td = _tmp_data((name, mutate))
        if cls is None:
            from hanghang.engine.scale_ledger import ScaleLedger
            book = ScaleLedger(td)
        else:
            book = cls(td)
        problems = book.validate()          # 不许抛
        assert any(needle in p or "不是映射" in p for p in problems), (
            f"{name} 里混了字符串却没报出来：{problems[:3]}")


def test_scalar_where_a_mapping_belongs_does_not_kill_every_exit():
    """`missing: "缺"` 曾让 `IndustryDatabase()` 构造函数直接崩

    评审六轮第 2 条。崩在 `_load()` 意味着 `industry scale` / `strategy` /
    `baseline` / `io` / `export` / `/api/industry-db` **全部一起挂** ——
    一份只读旁证连坐整个 M11 出口，正是本仓库自己写过的那条反面。

    而且"写歪"与"没填"必须分开：前者要改数据，后者要补数据。
    混成一句"未填原因"，等于两件事都没说。
    """
    from hanghang.engine.scale_ledger import ScaleLedger
    from hanghang.engine.strategy_view import StrategyView

    td = _tmp_data(
        ("industry-scales.yaml", lambda d: d["scales"][0].update({"missing": "缺"})),
        ("industry-strategy.yaml",
         lambda d: d["partitions"][0].update({"missing": "缺"})),
    )
    # 构造函数不许抛
    ledger = ScaleLedger(td)
    view = StrategyView(td)
    assert any("映射" in p for p in ledger.validate()), ledger.validate()[:3]
    assert any("映射" in p for p in view.validate()), view.validate()[:3]
    # 写歪 ≠ 没填：不许冒充"说不出原因"
    pid = next(iter(view.entries))
    assert view.missing_reason(pid, "value_chain") == ""
    # 整条出口链不许连坐
    db = IndustryDatabase(data_dir=td)
    db.compute()                       # 汇总口径走一遍
    db.scales.visibility_all()         # 六口径可见度走一遍
    db.money.position("sector-household")   # 资金流头寸走一遍
    db.strategy.summary()              # 战略视图汇总走一遍


def test_string_value_chain_is_not_split_into_characters():
    """`value_chain: "规划设计→施工"` 曾被 `list()` 拆成一个个汉字

    拆出来的是一串"看着非空、其实没有意义"的项 —— 比报错更难查：
    价值链长度校验照样通过（汉字够 3 个），利润池的 where 却永远对不上。
    """
    from hanghang.engine.strategy_view import StrategyView

    td = _tmp_data(("industry-strategy.yaml",
                    lambda d: d["partitions"][0].update(
                        {"value_chain": "规划设计→总包施工"})))
    view = StrategyView(td)
    row = view.row(view.entries and next(iter(view.entries)))
    assert row["value_chain"] == [], row["value_chain"]
    assert any("value_chain" in p and "字符串" in p for p in view.validate()), \
        view.validate()[:3]


def test_negative_declared_cannot_pass_reconciliation():
    """`declared_in_cny` 为负数时对账恒过 —— 一个符号手滑关掉了唯一能抓漏的那条

    评审六轮第 3 条。`abs(gap) / declared` 在 declared < 0 时是负数，
    **永远 ≤ 容差**，于是 status=ok、validate 一条不报。负的偏差率看着
    还挺像"略有偏差"，比报错坏得多。

    刻意不复用 `declared_zero` 的判词："声明了 0"（口径未统计）与
    "声明了负数"（写错了）是两件事。
    """
    td = _tmp_data(("industry-money-flows.yaml",
                    lambda d: next(n for n in d["nodes"]
                                   if n["id"] == "sector-household")
                    .update({"declared_in_cny": -1e14})))
    book = MoneyFlowBook(td)
    status = {(r["node"], r["side"]): r["status"] for r in book.reconcile()}
    assert status[("sector-household", "in")] == "invalid_declared", status
    assert any("sector-household" in p for p in book.validate()), book.validate()[:3]


def test_cli_reconciliation_never_prints_a_green_tick_for_zero_declared():
    """`declared = 0` 时 CLI 曾打 ✓（`ratio = abs(gap)/declared if declared else 0`）

    评审六轮第 4 条。engine 侧 `reconcile()` 早有 `declared_zero` 判词，
    CLI 却自己另算一遍，把比值硬置 0 再打绿勾 —— **同一条数据两个结论，
    人只会照着绿的那个看**。现在判词一律取 `reconcile().status`。
    """
    td = _tmp_data(("industry-money-flows.yaml",
                    lambda d: next(n for n in d["nodes"]
                                   if n["id"] == "sector-household")
                    .update({"declared_in_cny": 0})))
    out = subprocess.run(
        [sys.executable, os.path.join(ROOT, "src/hanghang/cli/main.py"),
         "industry", "money", "--node", "sector-household", "--data-dir", td],
        capture_output=True, text=True, cwd=ROOT)
    assert out.returncode == 0, out.stderr
    assert "Traceback" not in out.stderr, out.stderr
    line = next(ln for ln in out.stdout.splitlines() if "流入对账" in ln)
    assert "不参与对账" in line, line
    assert "✓" not in line, f"declared=0 不许打绿勾：{line}"


def test_cli_reconciliation_survives_written_garbage():
    """只读命令遇到写坏的 declared 不许 traceback，也不许假装成"未声明"

    评审六轮第 5 条：同一文件里 flow 金额已经改用 `_num()`，声明口径那半边漏了。
    「渲染路径与校验路径用同一套取值规则」只做了一半。
    """
    for bad in ("64e12", -1e14):
        td = _tmp_data(("industry-money-flows.yaml",
                        lambda d, b=bad: next(n for n in d["nodes"]
                                              if n["id"] == "sector-household")
                        .update({"declared_in_cny": b})))
        out = subprocess.run(
            [sys.executable, os.path.join(ROOT, "src/hanghang/cli/main.py"),
             "industry", "money", "--node", "sector-household", "--data-dir", td],
            capture_output=True, text=True, cwd=ROOT)
        assert out.returncode == 0, out.stderr
        assert "Traceback" not in out.stderr, out.stderr
        line = next(ln for ln in out.stdout.splitlines() if "流入对账" in ln)
        assert "数据写坏" in line, line
        assert "未声明" not in line, f"写坏 ≠ 未声明：{line}"


def test_share_only_input_actually_multiplies_intermediate():
    """`{from: x, share: 0.5}` 曾两个分支都返回 None —— 按文档写数据反而报错

    评审六轮第 6 条。docstring 写着"给 share 则乘中间投入总额"，代码却是
    `return None if not isinstance(...) else None`，两个分支都 None。
    于是合法数据被报"取不到金额"，同时"构成合计 vs 中间投入总额"再误报一条
    −100% 偏差。**按文档写数据却报错，比不支持更坏。**
    """
    from hanghang.engine.input_output import InputOutputBook

    book = InputOutputBook()
    # 找一个两端都有的账户做样板：中间投入 23 万亿，取一半
    pid = next((k for k, a in book.accounts.items()
                if book.term(a, "intermediate")), None)
    assert pid, "找不到带 intermediate 的样板账户"
    mid = book.term(book.accounts[pid], "intermediate")
    got = book._input_amount({"from": "x", "share": 0.5}, pid)
    assert got == mid * 0.5, (got, mid)
    # 没有中间投入总额时不编数：返回 None 让 validate 报「缺 intermediate」
    assert book._input_amount({"from": "x", "share": 0.5}, "不存在的分区") is None


# ------------------------------ 评审八轮：嵌套段的形状（顶层收口只收了一层）
def _write_yaml(td, name, mutate):
    """改临时 data 副本里的某个 yaml。用例必须落在文件上，不能 patch 内存对象。"""
    import yaml

    path = os.path.join(td, name)
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    mutate(data)
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, allow_unicode=True)


def test_nested_scalar_sections_never_crash_any_exit():
    """嵌套段写成标量：`(acc.get("intermediate") or {}).get("derived")` 崩

    评审八轮第 1 条。`or {}` 对**标量**不生效（int 是真值），于是 `.get` 直接
    打在 int 上 —— 而同一文件的 `term()` 对这个字段有 isinstance 保护。
    同一份数据两种结局：金额读成 None，derived 那行 traceback。

    它同时打崩四条出口：`industry check` / `compute()` / `render_text()` /
    `/api/industry-db`。所以修在入口（`_normalize_account`），
    而不是在四个消费点各加一次 isinstance。
    """
    from hanghang.engine.input_output import InputOutputBook

    cases = [
        ("industry-input-output.yaml", "accounts", "intermediate"),
        ("industry-input-output.yaml", "accounts", "output"),
        ("industry-input-output.yaml", "accounts", "value_added"),
        ("industry-strategy.yaml", "partitions", "ai_frontier"),
        ("industry-strategy.yaml", "partitions", "division_of_labor"),
        ("industry-strategy.yaml", "partitions", "missing"),
    ]
    for name, section, key in cases:
        td = _tmp_data()
        _write_yaml(td, name, lambda d, s=section, k=key:
                    d[s][0].update({k: 1234567890}))
        db = IndustryDatabase(data_dir=td)
        problems = db.validate()                 # CI 闸：不许 traceback
        assert any(key in p and "映射" in p for p in problems), (
            f"{name}:{key} 写成标量却没报出来：{problems[:3]}")
        db.compute()                             # /api/industry-db 与导出都走它
        if name == "industry-input-output.yaml":
            book = InputOutputBook(td)
            book.dedup_ledger()
            book.input_plan()


def test_nested_list_sections_never_crash_and_are_reported():
    """嵌套列表写成字符串/混字符串：`inputs: 建材` 被逐字迭代成「建」「材」

    评审八轮第 2 条。`dict_list` 只加在顶层 `accounts` 上，
    `for it in (acc.get("inputs") or [])` 完全绕过它 —— 同一文件里
    4-a 走 dict_list、4-b 走裸列表，**同一次校验两个口径**。
    """
    from hanghang.engine.input_output import InputOutputBook
    from hanghang.engine.official_baseline import OfficialBaseline

    for value, needle in (("建材", "应写成列表"), (["建材"], "不是映射")):
        td = _tmp_data()
        _write_yaml(td, "industry-input-output.yaml",
                    lambda d, v=value: d["accounts"][0].update({"inputs": v}))
        book = InputOutputBook(td)
        problems = book.validate()               # 不许崩
        assert any(needle in p for p in problems), (value, problems[:3])
        book.dedup_ledger()
        book.input_plan()
        IndustryDatabase(data_dir=td).compute()

    # series 是嵌套在 benchmark 里的列表：顶层的 dict_list 管不到它
    td = _tmp_data()
    _write_yaml(td, "industry-official-baseline.yaml",
                lambda d: d["benchmarks"][0]["series"].append("坏"))
    base = OfficialBaseline(td)
    assert any("series" in p and "不是映射" in p for p in base.validate()),         base.validate()[:3]
    base.yoy(base.benchmarks[0]["id"])           # 消费点也不许崩


def test_one_shape_defect_is_reported_once():
    """同一条结构问题不许报两遍：两遍会让人去修一个不存在的第二处

    评审八轮第 5 条。`ScaleLedger.validate()` 与 `cross_check()` 都接了
    `load_problems`，而 `IndustryDatabase.validate()` 把两者拼进同一个列表 ——
    `scales: [坏行]` 会打出两条一模一样的「有 1 项不是映射」。
    其余四本账都只有一处出口，只有这一本有两条。
    """
    td = _tmp_data()
    _write_yaml(td, "industry-scales.yaml",
                lambda d: d["scales"].append("坏行"))
    problems = IndustryDatabase(data_dir=td).validate()
    hits = [p for p in problems if "不是映射" in p]
    assert len(hits) == 1, f"同一条结构问题报了 {len(hits)} 遍：{hits}"


def test_strategy_row_never_contradicts_its_own_validate():
    """`validate()` 说"应写成映射"而 `row()` traceback —— 同一份数据两个结论

    评审八轮第 4 条。`_load()` 里 `_check_sections` 确实记了 problem，
    但 `row()` 自己又 `or {}` 兜了一次（对 str 不生效），于是
    `industry check` 报错、`industry strategy` 却崩。
    这正是 `_shape.py` 自己 docstring 里写的那句话，只是换了个位置发生。
    """
    from hanghang.engine.strategy_view import StrategyView

    td = _tmp_data()
    _write_yaml(td, "industry-strategy.yaml",
                lambda d: d["partitions"][0].update({"ai_frontier": "强"}))
    view = StrategyView(td)
    pid = next(iter(view.entries))
    row = view.row(pid)                          # 不许崩
    assert row["ai_strong"] == []
    assert any("ai_frontier" in p for p in view.validate())
    view.rows()
    view.summary()


def test_web_panel_degrades_to_503_not_500_on_shape_defect():
    """构造期兜住了、`compute()` 没兜 —— 面板会是 500 而不是 503

    评审八轮「影响」段：`_init_engines` 只包住构造，而 `compute()` 才去碰
    嵌套段。只兜一半的后果是：坏数据把整个只读面板打成 500，
    与「旁路数据坏了不能拖垮主面板」的口径不一致。
    """
    source = open(os.path.join(ROOT, "src/hanghang/web/server.py"),
                  encoding="utf-8").read()
    body = source.split("def _api_industry_db")[1].split("def _do_route")[0]
    assert "try:" in body and "db.compute()" in body, (
        "compute() 必须包住：构造期兜住不等于出口兜住")
    assert "503" in body, "形状读不出来要回 503（旁路降级），不是 500"


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ✅ {name}")
    print("✅ 六口径规模账 + 资金流守恒账测试通过")
