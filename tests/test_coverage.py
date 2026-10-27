"""行业岗位覆盖进度测试：目标全集(coverage-target) vs 当前覆盖(unit-index)

验证：
1. coverage-target 目标全集清单可被正确加载与解析。
2. 已注册 14 行业自动判为已覆盖(行业覆盖率>0)，行业覆盖率与岗位覆盖率能正常计算。
3. pending 行业未被误判为已覆盖，且能列出缺口(gaps)。
4. 数据驱动：新增/覆盖行业计数口径自洽(行业覆盖=已注册目标行业，岗位覆盖>=当前注册岗位)。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from hanghang.engine import Registry
from hanghang.engine.coverage import CoverageTracker


def test_target_file_loaded():
    """目标全集清单可加载，含 已注册 + 待补 两类"""
    t = CoverageTracker()
    assert len(t.targets) > 0
    statuses = {x.get("status") for x in t.targets}
    assert "pending" in statuses  # 存在待覆盖行业(分母有缺口)


def test_covered_industries_positive_and_consistent():
    """行业覆盖率>0，且已覆盖行业数 >= 已注册单元中纳入目标的行业数"""
    t = CoverageTracker()
    reg = Registry()
    s = t.compute()
    # 已覆盖行业数>0 且与注册单元数一致(14个均已纳入目标全集)
    assert s["covered_industries"] >= 1
    assert s["industry_coverage"] > 0
    # 全覆盖率不可能为100%(存在 pending 缺口)
    assert s["industry_coverage"] < 1.0
    # 覆盖行业 ≤ 已注册单元数(每个已注册单元至多对应一个目标行业)
    reg_count = len(reg.all_units())
    assert s["covered_industries"] <= reg_count


def test_role_coverage_bounds():
    """岗位覆盖率在 0-1 之间，覆盖岗位数与注册岗位自洽"""
    t = CoverageTracker()
    reg = Registry()
    s = t.compute()
    assert 0.0 <= s["role_coverage"] <= 1.0
    # 岗位覆盖(分子)至少等于全部注册岗位数(已覆盖行业按实际 roles 计)
    total_roles = sum(len(u.roles) for u in reg.all_units())
    assert s["covered_roles"] == total_roles
    assert s["role_coverage"] > 0


def test_pending_gaps_listed():
    """待补(pending)行业出现在缺口清单中，registered 不在其中"""
    t = CoverageTracker()
    gaps = t.gaps()
    assert gaps, "目标全集应存在待补行业"
    names = {g["name"] for g in gaps}
    # 已覆盖行业不应出现在缺口里
    for g in gaps:
        assert g["status"] != "registered"
    assert "人力资源" not in names  # 高优先级已覆盖，不再出现在缺口
    assert "金融投资" in names  # 代表性子集(仍待补)


def test_occupation_db_is_baseline_authority():
    """岗位基线以 M11 职业库为准：coverage 分母不随 coverage-target 手写岗位漂移"""
    from hanghang.engine.industry_db import IndustryDatabase
    db = IndustryDatabase()
    t = CoverageTracker(industry_db=db)
    s = t.compute()
    # 逐行业核对：已注册行业岗位基线 == 该分区基线职业数
    for row in s["rows"]:
        occ = db.partition(row["id"])
        if occ is None or row["status"] != "registered":
            continue
        baseline_occs = [o for o in db.members_of(row["id"])
                         if o.get("baseline_occupation")]
        if baseline_occs:
            assert row["roles"]["baseline"] == len(baseline_occs), row["id"]
            assert row["roles"]["baseline_source"] == "occupation", row["id"]


def test_role_baseline_total_equals_occupation_db_sum():
    """总量断言：分母必须等于「职业库基线合计」，而不是刚好等于分子那几个数

    旧断言比的是 roles.baseline（分母）与基线职业数（分子口径），恒真且测不出
    industry_db 失效。这里直接比 compute() 的总分母与职业库独立算出的合计。
    """
    from hanghang.engine.industry_db import IndustryDatabase
    db = IndustryDatabase()
    t = CoverageTracker(industry_db=db)
    s = t.compute()

    # 独立复算：权威源（职业库基线，口径同 CoverageTracker）+ 兜底（无登记分区）
    authoritative = sum(
        1 for o in db.occupations
        if o.get("baseline_occupation")
        and db.partition(o.get("unit_id") or "") is not None)
    registered_ids = {p.get("id") for p in db.partitions}
    fallback = 0
    fallback_only = 0
    for target in t.targets:
        unit = t._registered_map().get(target.get("name", ""))
        fallback_only += len(unit.roles) if unit else len(
            target.get("target_roles", []) or [])
        if target.get("id") in registered_ids:
            continue
        fallback += len(unit.roles) if unit else len(
            target.get("target_roles", []) or [])
    assert s["total_role_baseline"] == authoritative + fallback
    # 权威源必须真的被用上：总基线不得等于「全量兜底」
    assert s["total_role_baseline"] != fallback_only
    # 分子：已注册行业按实际注册岗位计
    assert s["covered_roles"] == sum(
        len(u.roles) for u in t._registered_map().values())


def test_stale_baseline_is_reported_not_silent():
    """分区有职业登记但全部非基线 → 兜底必须可见（problems）"""
    from hanghang.engine.coverage import CoverageTracker as CT

    class FakeDB:
        @staticmethod
        def partition(pid):
            return {"id": pid} if pid == "x" else None

        @staticmethod
        def members_of(pid):
            return [{"id": "only-ext", "unit_id": pid,
                     "baseline_occupation": False}]

    t = CT(industry_db=FakeDB())
    source = t._baseline_source("x", has_unit=True)
    assert source == "stale", source

    class FakeTracker(CT):
        def _load_targets(self):
            self.targets = [{"id": "x", "name": "占位行业", "category": "c"}]
            self.version, self.updated_at = "0", ""

    ft = FakeTracker(industry_db=FakeDB())
    s = ft.compute()
    assert s["rows"][0]["roles"]["baseline_source"] == "stale"
    assert any("baseline_occupation" in p for p in s["problems"])
    # 有登记但全非基线时不得回落 roles 计数（宁可为 0 也不能冒充）
    assert s["rows"][0]["roles"]["baseline"] == 0


def test_text_render_smoke():
    """coverage 文本渲染可执行且包含核心口径"""
    t = CoverageTracker()
    text = t.render_text()
    assert "行业覆盖" in text and "岗位覆盖" in text
    assert "coverage-target" in text


if __name__ == "__main__":
    test_target_file_loaded()
    test_covered_industries_positive_and_consistent()
    test_role_coverage_bounds()
    test_pending_gaps_listed()
    test_occupation_db_is_baseline_authority()
    test_role_baseline_total_equals_occupation_db_sum()
    test_stale_baseline_is_reported_not_silent()
    test_text_render_smoke()
    print("✅ 行业岗位覆盖进度测试通过")
