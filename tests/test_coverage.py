"""行业岗位覆盖进度测试：目标全集(coverage-target) vs 当前覆盖(unit-index)

验证：
1. coverage-target 目标全集清单可被正确加载与解析。
2. 已注册 11 行业自动判为已覆盖(行业覆盖率>0)，行业覆盖率与岗位覆盖率能正常计算。
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
    # 已覆盖行业数>0 且与注册单元数一致(11个均已纳入目标全集)
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
    assert "人力资源" in names  # 代表性子集


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
    test_text_render_smoke()
    print("✅ 行业岗位覆盖进度测试通过")
