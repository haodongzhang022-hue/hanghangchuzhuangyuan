"""行业补全与视角分离测试（M11 第三轮：口径补全 + 多视角）

这组断言守的是"漏掉的职业"和"被误丢的通道"两类问题：
1. 之前没统计到的职业（主播/陪玩/电竞/骑手）必须登记在册，且有归属分区。
2. 不直接付费的人群（军人/消防/矿工/家庭照护）不许因为"不好收费"被丢掉：
   职业照样登记、通道单独标记、就业口径照样计。
3. 多视角 ≠ 多分区：同一分区可被多根轴引用，不是给每个视角复制一份数据。
4. 承接通道只统计实测，写错枚举要报出来，不许静默回落到 paid_direct。
5. 就业口径：有人没产值（军队/家庭无酬）也要有数，缺数留空而不是填 0。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from hanghang.engine.industry_db import (
    ACCESS_SIDES, AXES, DEFAULT_ACCESS, IndustryDatabase,
)


def _db():
    return IndustryDatabase()


# --------------------------------------------------------------- 补全职业
def test_streaming_and_esports_occupations_registered():
    """直播/电竞/陪玩这些"新出现的职业"必须在册，不能被旧口径漏掉"""
    db = _db()
    ids = {o["id"] for o in db.occupations}
    for oid in ("streamer", "live-stream-operator", "esports-player",
                "game-companion", "esports-operator"):
        assert oid in ids, oid
    assert db.partition("esports-live") is not None
    members = {o["id"] for o in db.members_of("esports-live")}
    assert "streamer" in members
    # 直播运营挂在内容创作（带货/内容侧），不挤进电竞分区
    op = db.occupation("live-stream-operator")
    assert op["unit_id"] == "content-creation"


def test_gig_and_platform_occupations_registered():
    """骑手/快递/网约车这类平台零工以前没进库，现在必须有"""
    db = _db()
    ids = {o["id"]: o for o in db.occupations}
    for oid in ("delivery-rider", "courier", "ride-hailing-driver"):
        assert oid in ids, oid
    assert ids["delivery-rider"]["unit_id"] == "logistics-supply"


def test_no_market_occupations_are_registered_not_dropped():
    """军队/消防/采矿/家庭照护：不直接收费，但必须登记在册"""
    db = _db()
    ids = {o["id"] for o in db.occupations}
    must = {"military-officer", "soldier", "civilian-staff-mil", "firefighter",
            "underground-miner", "open-pit-miner", "seafarer",
            "homemaker", "family-caregiver"}
    assert must <= ids, must - ids


def test_evaluated_partition_still_holds_occupations():
    """evaluated（不建单元）≠ 忽略：分区里的职业照样登记、照样有就业口径"""
    db = _db()
    for pid in ("mining-resources", "public-safety", "utilities",
                "water-marine", "international-org"):
        p = db.partition(pid)
        assert p and p["status"] == "evaluated"
        assert db.members_of(pid), f"{pid} 无成员职业（又被悄悄丢掉了）"
        assert p.get("employment") is not None, f"{pid} 缺就业口径"


# --------------------------------------------------------------- 承接通道
def test_access_defaults_to_paid_direct_without_backfill():
    """老数据不写 access = 现金市场直连，不必为 139 条补字段"""
    db = _db()
    bare = [o for o in db.occupations if "access" not in o]
    assert bare, "应存在未写 access 的老职业（证明缺省语义还在用）"
    assert all(db.access_of(o) == DEFAULT_ACCESS for o in bare)


def test_access_distribution_is_measured_and_counts_non_market():
    """通道分布按实测，非市场/家庭无酬同样计入 n（不许被悄悄剔出分母）"""
    db = _db()
    dist = db.access_distribution()
    assert dist["n"] == len(db.linked_occupations())
    assert dist["non_market"] > 0 and dist["household"] > 0
    assert round(sum(dist[k] for k in ACCESS_SIDES), 0) == 100


def test_unknown_access_value_is_reported():
    """access 写错（例如连字符）会静默回落 paid_direct，必须报出来"""
    db = _db()
    db.occupations[0]["access"] = "non-market"
    problems = db.validate()
    assert any("access=non-market" in p or "non-market" in p for p in problems)


# --------------------------------------------------------------- 多视角
def test_axes_allow_one_partition_many_views():
    """多视角 ≠ 多分区：同一分区可出现在多根轴下，数据只存一份"""
    db = _db()
    assert len(db.by_axis("occupation")) == len(db.partitions)
    narrow = [p for p in db.partitions if len(p.get("axes") or AXES) < len(AXES)]
    assert narrow, "应存在收窄视角的分区（无行业/税目口径的职能型分区）"
    for p in narrow:
        assert set(p["axes"]) <= set(AXES)
    # 分区 id 不因视角而重复
    ids = [p["id"] for p in db.partitions]
    assert len(ids) == len(set(ids))


def test_unknown_axis_is_reported():
    db = _db()
    db.partitions[0]["axes"] = ["occupation", "industry", "wrong-axis"]
    problems = db.validate()
    assert any("wrong-axis" in p for p in problems)


def test_empty_axes_is_reported():
    """空视角 = 任何看板都查不到，但覆盖率不会变红，属于暗沟"""
    db = _db()
    db.partitions[0]["axes"] = []
    problems = db.validate()
    assert any("axes 为空" in p for p in problems)


# --------------------------------------------------------------- 就业口径
def test_employment_present_for_every_partition():
    """每个分区都要有就业口径：有人没产值也算数，绝不因为没有 gdp 一起丢"""
    db = _db()
    missing = [p["id"] for p in db.partitions if p.get("employment") is None]
    assert not missing, missing
    s = db.compute()
    assert s["employment_total_wan"] > 50000
    assert s["employment_known_partitions"] == len(db.partitions)


def test_employment_zero_and_missing_are_different():
    """0 与"没口径"不是一回事：填 0 会被当成实测，必须能守住"""
    db = _db()
    db.partitions[0]["employment"] = -1
    assert any("employment" in p for p in db.validate())
    db.partitions[0]["employment"] = None
    assert not any("employment" in p for p in db.validate())


def test_gdp_null_but_employment_present():
    """无市场产值口径的分区（政务/行政）也要有人数"""
    db = _db()
    for pid in ("admin-office", "public-affairs"):
        p = db.partition(pid)
        assert p["gdp_cny"] is None
        assert p.get("employment")


# --------------------------------------------------------------- 集成
def test_real_data_still_self_consistent():
    """补完数据后自检必须干净：新增字段不能引入新的脏数据"""
    assert _db().validate() == []


def test_coverage_denominators_unchanged_by_completion():
    """补全不虚增分母：baseline 只收能建单元的职业，画像类职业进全量登记"""
    db = _db()
    s = db.compute()
    assert s["baseline_occupations"] == s["linked_baseline_occupations"]
    assert s["total_occupations"] > s["baseline_occupations"], \
        "非基线职业（不建单元的现场岗/无酬劳动）必须登记但不算单元覆盖分子"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ✅ {name}")
    print("✅ 行业补全与视角分离测试通过")
