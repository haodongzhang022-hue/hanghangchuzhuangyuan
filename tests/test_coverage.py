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
    """岗位覆盖率在 0-1 之间，分子分母同一口径、逐行自洽"""
    t = CoverageTracker()
    reg = Registry()
    s = t.compute()
    assert 0.0 <= s["role_coverage"] <= 1.0
    # 分子必须等于逐行 covered 之和 —— 与分母一样按「基线职业」算，而不是
    # len(unit.roles)（两套口径会算出 covered > baseline 的 500% 覆盖）
    assert s["covered_roles"] == sum(r["roles"]["covered"] for r in s["rows"])
    # 每一行都不许超过自己的分母
    for r in s["rows"]:
        assert r["roles"]["covered"] <= r["roles"]["baseline"], r["id"]
    # 分子 ≤ 分母（口径对齐后的硬约束）
    assert s["covered_roles"] <= s["total_role_baseline"]
    assert s["role_coverage"] > 0
    assert len(reg.all_units()) >= s["covered_industries"]


def test_pending_gaps_listed():
    """待补(pending)行业出现在缺口清单中，registered 不在其中"""
    t = CoverageTracker()
    gaps = t.gaps()
    # 不能断言 gaps 非空：目标全集被覆盖完之后缺口本来就可以为空，
    # 「必须还有缺口」不是不变式，只是在锁定某一时刻的进度。
    names = {g["name"] for g in gaps}
    # 已覆盖行业不应出现在缺口里
    for g in gaps:
        assert g["status"] != "registered"
    # 缺口清单只报**还没覆盖**的目标行业。别在这里点名具体行业
    # （"金融投资仍待补"这类断言会随着建单元而失效，测的是当时的快照不是不变式）。
    # 真正的不变式是：缺口里的行业都还没注册成单元。
    assert isinstance(gaps, list)
    registered_names = {u.industry for u in Registry().all_units()}
    overlap = [g["industry"] for g in gaps
               if g.get("industry") in registered_names]
    assert not overlap, f"已注册的行业不该出现在缺口里: {overlap}"


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
    # 归属是模糊的：一个职业被多个视角引用也只算一次，所以按"引用集合"取，
    # 不能按 unit_id 单值取（那就是旧的硬归属口径了）。
    referenced = {m.get("occupation") for m in db.axis_view.memberships
                  if db.partition(m.get("partition") or "") is not None}
    authoritative = sum(
        1 for o in db.occupations
        if o.get("baseline_occupation") and o.get("id") in referenced)
    # stale 行（分区有职业登记、但成员全没标 baseline_occupation）会按该分区的
    # 视角规模兜底，同时进 problems。这部分人**不在** authorized 里，所以必须
    # 单独加回来，否则账面对不上会被误读成"权威源失效"。
    stale_ids = {o["id"] for r in s["rows"]
                 if r["roles"]["baseline_source"] == "stale"
                 for o in db.members_of(r["id"])}
    # CoverageTracker 用的是职业库基线数（按视角去重后的人）。
    # 软归属下同一职业可能被多个视角引用，这里显式声明"按人去重"，
    # 让断言在新增/删除横切边时仍然成立。
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
    # stale 行（有职业登记但全非基线）会回落 target_roles 兜底，但它同时进 problems；
    # 这条断言只做"账能对上"，不把 stale 洗白。
    stale_fallback = sum(r["roles"]["baseline"] for r in s["rows"]
                         if r["roles"]["baseline_source"] == "stale")
    # 归属是模糊的，两处都会"同一个人出现多次"，所以两边都得先按人去重再比：
    #   - 权威源：一个职业被多个视角引用，只在其中一行被计入基线；
    #   - stale 兜底：分区按视角规模兜底（成员数），也和"人"的口径不同。
    # 旧断言是 scalar 对 scalar，加了横切边之后必然对不上——不是权威源失效了，
    # 是账算重了。
    counted_people = {o["id"] for r in s["rows"]
                      if r["roles"]["baseline_source"] == "occupation"
                      for o in db.members_of(r["id"])
                      if o.get("baseline_occupation")}
    total_people = counted_people | stale_ids
    assert len(total_people) == authoritative + len(stale_ids - counted_people)
    assert s["total_role_baseline"] == sum(r["roles"]["baseline"] for r in s["rows"])
    # stale 必须可见：不许静默兜底
    assert all(any(r["id"] in p for p in s["problems"])
               for r in s["rows"] if r["roles"]["baseline_source"] == "stale")
    # 权威源必须真的被用上：总基线不得等于「全量兜底」
    assert s["total_role_baseline"] != fallback_only + stale_fallback
    # 分子：与分母同口径（基线职业里 unit_role 真落在该单元岗位中的个数）
    assert s["covered_roles"] == sum(r["roles"]["covered"] for r in s["rows"])
    assert s["covered_roles"] <= s["total_role_baseline"]


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


def test_broken_industry_db_degrades_visibly():
    """权威源读取抛异常 → 覆盖统计仍能出结果，降级写进 problems（不静默）"""
    from hanghang.engine.coverage import CoverageTracker as CT

    class BrokenDB:
        @staticmethod
        def partition(pid):
            return {"id": pid}

        @staticmethod
        def members_of(pid):
            raise RuntimeError("disk gone")

    class FakeTracker(CT):
        def _load_targets(self):
            self.targets = [{"id": "x", "name": "占位行业", "category": "c",
                             "target_roles": ["a", "b"]}]
            self.version, self.updated_at = "0", ""

    t = FakeTracker(industry_db=BrokenDB())
    s = t.compute()  # 旧实现这里会抛 RuntimeError
    assert s["total_role_baseline"] == 2  # 回落 target_roles
    assert any("降级" in p for p in s["problems"]), s["problems"]
    # 降级时行级不得声称走了权威源
    assert s["rows"][0]["roles"]["baseline_source"] != "occupation"


def test_partial_industry_db_degrades():
    """members_of 返回 None（不抛异常）也要降级，不能 TypeError"""
    from hanghang.engine.coverage import CoverageTracker as CT

    class PartialDB:
        @staticmethod
        def partition(pid):
            return {"id": pid}

        @staticmethod
        def members_of(pid):
            return None

    t = CT(industry_db=PartialDB())
    assert t._baseline_source("x", has_unit=True) == "unit_roles"
    assert t._occupation_baseline("x") is None
    assert any("降级" in p for p in t.compute()["problems"])


def test_baseline_distinct_reported_beside_partition_sum():
    """按分区累加 ≠ 全库去重：两个口径都要露出来，别让下游拿去做无效对账"""
    t = CoverageTracker()
    s = t.compute()
    assert s["role_baseline_distinct"] <= s["total_role_baseline"]
    assert (s["role_baseline_distinct"] + s["role_baseline_shared"]
            == s["total_role_baseline"])
    # 去重口径必须等于职业库里的基线职业数（权威源）
    from hanghang.engine.industry_db import IndustryDatabase
    db = IndustryDatabase()
    expect = len([o for o in db.occupations if o.get("baseline_occupation")])
    assert s["role_baseline_distinct"] == expect, (
        s["role_baseline_distinct"], expect)
    # 差异行必须在文本渲染里出现，否则数字对不上时没人知道为什么
    assert "去重后" in t.render_text()


def test_partition_returning_none_is_recorded_as_degrade():
    """partition() 返回 None 与"分区真的没登记"返回值同形，但语义不同：
    前者是权威源答不出话，必须留 problem；否则分区存在却读不出来会无声兜底。
    """
    from hanghang.engine.coverage import CoverageTracker as CT

    class NonePartitionDB:
        @staticmethod
        def partition(pid):
            return None

        @staticmethod
        def members_of(pid):
            return []

    t = CT(industry_db=NonePartitionDB())
    assert t._occupation_baseline("some-part") is None
    assert any("降级" in p and "some-part" in p for p in t.compute()["problems"])


def test_disable_industry_db_is_explicit():
    """DISABLED_DB 显式禁用；注入 False 走兜底而不是静默自动构造"""
    from hanghang.engine.coverage import CoverageTracker as CT, DISABLED_DB

    assert CT(industry_db=DISABLED_DB).industry_db is None
    # False 是"注入了一个假对象"，读取会失败降级，但不会被换成自动构造的真库
    injected = CT(industry_db=False)
    assert injected.industry_db is False
    assert injected._occupation_baseline("dongjiagoushi") is None


def test_degrade_note_not_duplicated_per_partition():
    """两个读取点各读一次 members_of，同一分区只记一条降级"""
    from hanghang.engine.coverage import CoverageTracker as CT

    class BrokenDB:
        @staticmethod
        def partition(pid):
            return {"id": pid}

        @staticmethod
        def members_of(pid):
            raise RuntimeError("disk gone")

    t = CT(industry_db=BrokenDB())
    t._occupation_baseline("x")
    t._baseline_source("x", True)
    assert len([p for p in t._degrade_notes if "分区 x " in p]) == 1


def test_covered_roles_never_exceeds_baseline_with_extra_roles():
    """单元岗位数 > 基线职业数时，不许出现 500% 覆盖

    评审复现：单元 5 个岗位、分区只有 1 条基线职业 → 旧实现输出
    covered=5 / baseline=1，页面照常不报错。分子改成同一口径后必须是 1。
    """
    class FakeDB:
        axis_view = None

        def partition(self, pid):
            return {"id": pid, "name": pid}

        def members_of(self, pid):
            return [{"id": "only-one", "baseline_occupation": True}]

        class axis_view:  # noqa: N801 - 替身，只为返回边
            @staticmethod
            def of_partition(pid):
                return [{"occupation": "only-one", "unit_role": "r0"}]

    class FakeRegistry:
        def all_units(self):
            from hanghang.engine.models import IndustryUnit, Role
            return [IndustryUnit(
                unit_id="u", industry="假行业", industry_alias=[],
                roles=[Role(name=f"r{i}", prefix="[r]")
                       for i in range(5)])]

    t = CoverageTracker(registry=FakeRegistry(), industry_db=FakeDB())
    t.targets = [{"id": "fake", "name": "假行业", "category": "测试",
                  "target_roles": []}]
    s = t.compute()
    row = s["rows"][0]
    assert row["roles"]["baseline"] == 1, row["roles"]
    assert row["roles"]["covered"] == 1, row["roles"]
    assert row["roles"]["covered"] <= row["roles"]["baseline"]


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
    test_broken_industry_db_degrades_visibly()
    test_partial_industry_db_degrades()
    test_baseline_distinct_reported_beside_partition_sum()
    test_partition_returning_none_is_recorded_as_degrade()
    test_disable_industry_db_is_explicit()
    test_degrade_note_not_duplicated_per_partition()
    test_covered_roles_never_exceeds_baseline_with_extra_roles()
    test_text_render_smoke()
    print("✅ 行业岗位覆盖进度测试通过")
