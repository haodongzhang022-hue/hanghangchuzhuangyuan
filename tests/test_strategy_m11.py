#!/usr/bin/env python3
"""M11 行业战略视图（大局观与战略视角）

用户这一轮把粒度红线说清楚了：**细节只到岗位和角色，不到更具体**——
剩下的是 AI 在对应岗位上明确职责后充当角色。所以这一层守的不是"写得多细"，
而是"有没有越界、有没有落到岗位上"：

  1. **每个分区都要有落点**：漏一个 = 这个行业只有数字没有判断，覆盖率不会变红。
  2. **粒度越界要报**：出现 steps/sop/prompt/kpi/persona 即报。写死的那一版
     职责，一定比市场慢半年，而且再没人回来改。
  3. **不许重复存金额**：战略层只放判断，金额回 partition 与六口径账。
  4. **role_focus 必须落在本分区真实岗位**：已建单元对 unit-index 的 roles，
     待建分区对 planned_roles。落不到岗位的战略是一句没人负责的口号。
  5. **空段要写原因**：说不出缺什么，等于保证它永远缺。
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

from hanghang.engine import industry_schema                       # noqa: E402
from hanghang.engine.industry_db import IndustryDatabase           # noqa: E402
from hanghang.engine.strategy_view import StrategyView, SECTIONS    # noqa: E402


def _db():
    return IndustryDatabase()


# ------------------------------------------------- 1. 落点：一个都不能少
def test_every_partition_has_strategy_view():
    """41 个分区每一个都要有战略视图：漏一个就是只有数字没有判断"""
    db = _db()
    missing = [p["id"] for p in db.partitions if p["id"] not in db.strategy.entries]
    assert not missing, f"这些分区没有行业战略视图: {missing}"
    assert db.strategy.loaded, "战略视图账本是空的（文件在但没内容）"


def test_dangling_entry_is_reported():
    """战略视图里写了一个不存在的分区：悬空条目必须报（永远查不到）"""
    db = _db()
    db.strategy.entries["no-such-partition"] = {"partition": "no-such-partition"}
    problems = db.strategy.validate()
    db.strategy.entries.pop("no-such-partition")
    assert any("no-such-partition" in x and "悬空" in x for x in problems), problems


def test_missing_partition_is_reported():
    """从战略视图里摘掉一个分区：必须报「只有数字、没有判断」"""
    db = _db()
    saved = db.strategy.entries.pop("manufacturing")
    problems = db.strategy.validate()
    db.strategy.entries["manufacturing"] = saved
    assert any("manufacturing" in x and "没有行业战略视图" in x for x in problems), problems


# ------------------------------------------------- 2. 粒度红线
def test_granularity_violation_is_reported():
    """写到"怎么做"就是越界：工序/话术/KPI 由 AI 上岗后按职责补"""
    db = _db()
    e = db.strategy.entries["construction-eng"]
    e["steps"] = ["第一步：打开图纸"]
    problems = db.strategy.validate()
    e.pop("steps")
    assert any("steps" in x and "粒度" in x for x in problems), problems

    # 提示词也是同一类越界：写死的提示词会把判断压成模板
    e["profit_pool"][0]["prompt"] = "请按以下格式输出"
    problems = db.strategy.validate()
    e["profit_pool"][0].pop("prompt")
    assert any("prompt" in x and "粒度" in x for x in problems), problems


def test_amount_fields_are_rejected():
    """战略层不许重复存金额：同一件事存两份，迟早对不上"""
    db = _db()
    e = db.strategy.entries["manufacturing"]
    e["gdp_cny"] = 33000000000000
    problems = db.strategy.validate()
    e.pop("gdp_cny")
    assert any("gdp_cny" in x and "金额" in x for x in problems), problems


# ------------------------------------------------- 3. 岗位落点
def test_role_focus_must_exist_in_partition():
    """战略结论必须落到本分区真实岗位：落不到就是一句没人负责的口号"""
    db = _db()
    # 已建单元：对 unit-index 的 roles
    e = db.strategy.entries["dongjiagoushi"]
    e["role_focus"] = ["architect", "chief-happiness-officer"]
    problems = db.strategy.validate()
    e["role_focus"] = ["architect", "developer"]
    assert any("chief-happiness-officer" in x for x in problems), problems

    # 待建分区：对 planned_roles
    e2 = db.strategy.entries["translation"]
    saved = list(e2["role_focus"])
    e2["role_focus"] = ["chief-translator"]
    problems = db.strategy.validate()
    e2["role_focus"] = saved
    assert any("chief-translator" in x for x in problems), problems


def test_role_focus_borrows_nothing_from_other_partitions():
    """岗位名是分区内命名：live_host 在 content-creation 存在，不代表别的分区也能用"""
    db = _db()
    e = db.strategy.entries["translation"]
    saved = list(e["role_focus"])
    e["role_focus"] = ["live_host"]      # 这个岗位只属于内容创作 / 直播
    problems = db.strategy.validate()
    e["role_focus"] = saved
    assert any("live_host" in x for x in problems), problems


def test_every_role_focus_is_valid_in_real_data():
    """真实数据必须全部落得住：宁可漏报，不可误报"""
    db = _db()
    bad = {r["partition"]: r["role_focus_dangling"] for r in db.strategy.rows()
           if r["role_focus_dangling"]}
    assert not bad, f"这些战略落点指向不存在的岗位: {bad}"


# ------------------------------------------------- 4. 判断本身的完整性
def test_profit_pool_must_be_inside_own_chain():
    """利润池指向一个自己链条上不存在的环节，等于说钱沉在别处"""
    db = _db()
    e = db.strategy.entries["food-beverage"]
    saved = e["profit_pool"]
    e["profit_pool"] = [{"where": "火星殖民", "why": "编的"}]
    problems = db.strategy.validate()
    e["profit_pool"] = saved
    assert any("火星殖民" in x for x in problems), problems


def test_profit_pool_needs_where_and_why():
    """只有环节没有原因，等于没说为什么钱在那儿"""
    db = _db()
    e = db.strategy.entries["legal-services"]
    saved = e["profit_pool"]
    e["profit_pool"] = [{"where": "诉讼与仲裁"}]
    problems = db.strategy.validate()
    e["profit_pool"] = saved
    assert any("缺 where 或 why" in x for x in problems), problems


def test_value_chain_needs_three_stages():
    """少于 3 段谈不上价值链，只是把一件事换个说法"""
    db = _db()
    e = db.strategy.entries["manufacturing"]
    saved = e["value_chain"]
    e["value_chain"] = ["生产"]
    problems = db.strategy.validate()
    e["value_chain"] = saved
    assert any("value_chain" in x and "3 段" in x for x in problems), problems


def test_ai_frontier_needs_all_three_bands():
    """强/弱/边界三档缺一档，就说不清 AI 该停在哪"""
    db = _db()
    e = db.strategy.entries["healthcare"]
    saved = dict(e["ai_frontier"])
    e["ai_frontier"] = {"strong": ["随访"], "weak": ["诊断"]}
    problems = db.strategy.validate()
    e["ai_frontier"] = saved
    assert any("boundary" in x for x in problems), problems


def test_division_of_labor_needs_both_sides():
    """只写人管什么，等于把 AI 那一侧默认成"谁都行"""
    db = _db()
    e = db.strategy.entries["admin-office"]
    saved = dict(e["division_of_labor"])
    e["division_of_labor"] = {"human_decides": ["用印与授权"]}
    problems = db.strategy.validate()
    e["division_of_labor"] = saved
    assert any("ai_fills" in x for x in problems), problems


def test_one_sided_blank_section_must_explain_itself():
    """空段不写原因 = 保证它永远空：说不出缺什么也要说出来"""
    db = _db()
    e = db.strategy.entries["esports"]
    saved = e.pop("leverage")
    problems = db.strategy.validate()
    e["leverage"] = saved
    assert any("esports" in x and "leverage" in x for x in problems), problems


def test_leverage_is_read_back_not_silently_dropped():
    """杠杆是字符串列表，消费方必须按字符串列表读。

    回归：row() 曾用 _dicts() 读 leverage（数据写的是 `- 领域know-how`），
    41 个分区的杠杆被整段过滤成空 —— `industry strategy` 打「杠杆: —」、
    strategy.csv 的 leverage 列 41 行全空 —— 而第 8 条校验看的是原始值
    （非空就跳过），于是一条问题都不报：数据静默消失、自检全绿。

    这里断言的不只是"删除后会报错"，而是"读出来就是有内容"，因为上一版的
    校验测不到"数据在、读出来是空"这种失效。
    """
    db = _db()
    rows = db.strategy.rows()
    assert rows, "没有任何分区行"
    empty = [r["partition"] for r in rows if not r["leverage"]]
    assert not empty, f"这些分区的 leverage 读出来是空的: {empty}"
    # 具体形状也要对：是字符串列表，不是被包成 dict 的东西
    for r in rows:
        assert all(isinstance(x, str) for x in r["leverage"]), (
            r["partition"], r["leverage"])
    # 数据里确实有、报告里也确实读到了：两边数量必须一致
    in_data = [p for p, e in db.strategy.entries.items() if e.get("leverage")]
    assert len(in_data) == len(rows), (len(in_data), len(rows))
    assert db.strategy.row("esports")["leverage"], "esports 的杠杆丢了"


def test_nonempty_raw_value_that_reads_empty_is_reported():
    """原始值非空、但消费方读出来是空 → 必须报。

    这是上一条的"护栏的护栏"：如果只修 row() 而不修校验，同样的形状错位
    （比如以后再有一个段被换成错误的归一函数）仍会静默消失。
    """
    db = _db()
    saved = db.strategy.row

    def broken_row(pid):
        r = saved(pid)
        r["leverage"] = []          # 模拟"数据在、读出来是空"
        return r

    db.strategy.row = broken_row
    try:
        problems = db.strategy.validate()
    finally:
        db.strategy.row = saved
    assert any("leverage" in x and "读出来是空的" in x for x in problems), problems


# 嵌套在映射里的四段：数据在 ai_frontier.strong / division_of_labor.human_decides
# 下，顶层没有同名键。第 9 条护栏如果用 e.get(section) 门控，这四段恒被跳过，
# 护栏看起来在守、实际是死代码（评审 2026-11-16 指出）。
NESTED_CONSUMER_PATHS = {
    "ai_strong": ("ai_frontier", "strong"),
    "ai_weak": ("ai_frontier", "weak"),
    "human_decides": ("division_of_labor", "human_decides"),
    "ai_fills": ("division_of_labor", "ai_fills"),
}


def test_nested_consumer_sections_are_guarded_too():
    """四个嵌套段逐一写歪 → 第 9 条必须报「读出来是空的」，不许静默消失。

    写歪的形态用**字符串**（而非空列表）：空列表会被第 5 条「缺 strong」直接抓到，
    走不到第 9 条；而字符串能过"非空"这一关，正是第 9 条要拦的那种失效。
    """
    db = _db()
    pid = "construction-eng"
    e = db.strategy.entries[pid]
    for section, path in NESTED_CONSUMER_PATHS.items():
        node = e
        for key in path[:-1]:
            node = node[key]
        saved = node[path[-1]]
        node[path[-1]] = "一整段字符串"          # 形状写歪、但非空
        try:
            # 前提：数据被读成空（缺陷真实发生）
            assert db.strategy.row(pid)[section] == [], (section, "未复现")
            problems = db.strategy.validate()
        finally:
            node[path[-1]] = saved
        assert any(pid in x and section in x and "读出来是空的" in x
                   for x in problems), (section, problems)
    # 恢复后真实数据必须重回干净
    assert db.strategy.validate() == []


def test_consumer_gate_shares_row_source():
    """第 9 条的门控必须按消费路径取原始值，不许退回 e.get(section)。

    这条直接钉两件事：
      1. _CONSUMER_PATHS 与 row() 的取值路径一致（四段是嵌套的，不是顶层的）；
      2. validate 源码里门控真的调用了 _raw_for_consumer —— 否则以后有人
         把它改回 e.get(section)，行为对真实数据毫无变化（数据都是对的），
         只有形状写歪时才会暴露，那又是一次"自检全绿、数据消失"。
    """
    import inspect
    for section, path in NESTED_CONSUMER_PATHS.items():
        assert StrategyView._CONSUMER_PATHS[section] == path, section
    src = inspect.getsource(StrategyView.validate)
    assert "_raw_for_consumer" in src, (
        "第 9 条门控没有走 _raw_for_consumer —— 嵌套四段会恒被跳过")
    # 门控是「if not <取值>(...section...): continue」这一对（可能跨行），
    # 不许再出现 e.get(section) 的旧写法。
    import re as _re
    gate = _re.findall(r"if not [^\n]*(?:\n\s+)?[^\n]*:\s*\n\s+continue", src)
    assert gate, ("没找到第 9 条的门控（源码变了，请同步本测试）\n" + src)
    section_gates = [g for g in gate if "section" in g]
    assert section_gates, ("门控没有按 section 遍历\n" + src)
    for g in section_gates:
        assert "_raw_for_consumer" in g, ("门控回到了 e.get(section) 一类写法\n" + g)
        assert "e.get(section)" not in g, ("门控回到了 e.get(section)\n" + g)


def test_empty_ledger_is_reported():
    """文件在、内容是注释 → 空账必须硬报，不能"每条校验都通过" """
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "industry-strategy.yaml")
        open(path, "w", encoding="utf-8").write("# 只有注释\n")
        sv = StrategyView(data_dir=td, partitions=[])
        assert sv.loaded is False
        assert any("空账" in x for x in sv.validate()), sv.validate()
        assert any("未读到" in x for x in StrategyView(
            data_dir=os.path.join(td, "nope"), partitions=[]).validate())


def test_real_data_is_clean():
    """真实数据必须零问题：战略视图不进"已知未完成"，一有缺口就红"""
    db = _db()
    assert db.strategy.validate() == []
    s = db.strategy.summary()
    assert s["covered"] == s["partitions"] == len(db.partitions)
    assert s["dangling_focus"] == 0


# ------------------------------------------------- 5. 与已有账本的关系
def test_strategy_reports_do_not_duplicate_amounts():
    """战略视图只有判断，没有金额：金额留 partition 与六口径账"""
    db = _db()
    for r in db.strategy.rows():
        for key in ("gdp_cny", "amount_cny", "employment"):
            assert key not in r, f"{r['partition']} 的战略视图出现了金额字段 {key}"


def test_cross_view_joins_strategy_with_measured_supply():
    """战略层的 AI 承接面要和实测供给结构并排放：两处都由人写，只有并排才看得出矛盾"""
    db = _db()
    rows = db.strategy.cross_view(db)
    assert len(rows) == len(db.partitions)
    d = next(r for r in rows if r["partition"] == "content-creation")
    # 内容创作实测 AI 占 50%，战略层给的是"哪几段站得住"，不是同一个数
    assert d["ai_share_measured"] is not None
    assert d["ai_strong"] >= 2 and d["ai_weak"] >= 1
    assert d["role_focus"] >= 1


# ------------------------------------------------- 6. 落库与 CLI
def test_schema_has_strategy_table():
    """结构单源：strategy_view 表必须在 TABLES 里，版本要跟着动"""
    names = industry_schema.tables()
    assert "strategy_view" in names, names
    assert industry_schema.SCHEMA_VERSION == "1.4.0"
    cols = industry_schema.columns_of("strategy_view")
    for c in ("partition", "value_chain", "profit_pool", "ai_boundary",
              "human_decides", "ai_fills", "role_focus"):
        assert c in cols, (c, cols)


def test_strategy_rows_are_written():
    """表要有行：空表等于"导进去了但什么都没有" """
    db = _db()
    c = industry_schema.counts(db, db.compute())
    assert c["strategy_view"] == len(db.partitions)


def test_cli_strategy_runs():
    out = subprocess.run(
        [sys.executable, os.path.join(ROOT, "src/hanghang/cli/main.py"),
         "industry", "strategy", "--top", "3"],
        capture_output=True, text=True, cwd=ROOT)
    assert out.returncode == 0, out.stderr
    assert "粒度红线" in out.stdout and "岗位落点" in out.stdout


def test_cli_strategy_partition_shows_pools():
    out = subprocess.run(
        [sys.executable, os.path.join(ROOT, "src/hanghang/cli/main.py"),
         "industry", "strategy", "--partition", "construction-eng"],
        capture_output=True, text=True, cwd=ROOT)
    assert out.returncode == 0, out.stderr
    assert "利润池" in out.stdout and "AI 边界" in out.stdout
    assert "cost_estimator" in out.stdout


def test_cli_strategy_gaps_runs():
    out = subprocess.run(
        [sys.executable, os.path.join(ROOT, "src/hanghang/cli/main.py"),
         "industry", "strategy-gaps"],
        capture_output=True, text=True, cwd=ROOT)
    assert out.returncode == 0, out.stderr
    assert "战略视图" in out.stdout


# ------------------------------------------------- 7. 上岗：判断要能到 AI 手上
def test_card_context_carries_industry_view():
    """行业判断必须进岗位卡的上下文块：否则 AI 上岗只知道岗位、不知道行业。

    这是整层的存在理由——AI 被派到造价员岗位上，知道要算量，但不知道这个行业的
    利润不在算量。判断留在数据文件里、没到工作现场，等于没写。
    """
    from hanghang.rolecard.loader import RoleCardStore
    store = RoleCardStore()
    card = store.get("dongjiagoushi", "architect")
    assert card is not None
    assert card.industry_view.get("position"), card.industry_view
    block = card.to_context_block()
    for label in ("行业位置", "利润池", "行业风险", "AI 边界", "必须人定"):
        assert label in block, (label, block)


def test_card_context_stays_stable_for_cache():
    """上下文块的缓存键只由层A决定：同岗位同数据必须输出恒定"""
    from hanghang.rolecard.loader import RoleCardStore
    store = RoleCardStore()
    a = store.get("dongjiagoushi", "developer").to_context_block()
    b = RoleCardStore().get("dongjiagoushi", "developer").to_context_block()
    assert a == b


def test_card_without_industry_view_still_renders():
    """战略视图缺失时岗位卡照常渲染：只少了行业那几行，不报错、不空卡"""
    from hanghang.rolecard.loader import RoleCardStore
    from hanghang.rolecard.models import RoleCard
    store = RoleCardStore()
    card = store.get("dongjiagoushi", "developer")
    card.industry_view = {}
    block = card.to_context_block()
    assert "岗位卡" in block and "行业位置" not in block


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ✅ {name}")
    print("全部通过")
