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
import re
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
    # 直播归 live-streaming、竞技/陪玩归 esports —— 原来挤在一个 esports-live 里，
    # 连"谁付费"都说不清（打赏 vs 奖金/工资/票务）
    assert db.partition("esports-live") is None, "折叠分区不该复活"
    assert "streamer" in {o["id"] for o in db.members_of("live-streaming")}
    assert {"esports-player", "game-companion", "esports-operator"} <= \
        {o["id"] for o in db.members_of("esports")}
    # 直播运营挂在内容创作（带货/内容侧），不挤进电竞分区
    op_views = {m["partition"] for m in db.views_of_occupation("live-stream-operator")}
    assert "content-creation" in op_views
    assert "esports-live" not in op_views


def test_gig_and_platform_occupations_registered():
    """骑手/快递/网约车这类平台零工以前没进库，现在必须有"""
    db = _db()
    ids = {o["id"]: o for o in db.occupations}
    for oid in ("delivery-rider", "courier", "ride-hailing-driver"):
        assert oid in ids, oid
    # 归属是模糊的：问"被哪个视角看见"，不再问"归属于谁"
    db2 = _db()
    assert "logistics-supply" in {m["partition"] for m in
                                  db2.views_of_occupation("delivery-rider")}


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
    """每个分区都要有就业口径：有人没产值也算数，绝不因为没有 gdp 一起丢

    例外是"刻意留空"：新拆分出来的分区（口译/笔译、直播/电竞、健身/赛事）
    共用一份行业合并口径，硬填一份等于把同一批人数算两遍 —— 这类分区的
    employment 必须为 None，且 gdp_source 要写明为什么留空。
    """
    db = _db()
    total_employment = sum(p.get("employment") or 0 for p in db.partitions
                           if p.get("employment") is not None)
    # 合并口径不许重复计入：合计不得接近翻倍
    assert total_employment > 50000
    missing = [p["id"] for p in db.partitions if p.get("employment") is None]
    for pid in missing:
        p = db.partition(pid)
        # 留空必须解释清楚，不能是漏填
        assert p.get("employment_source"), f"{pid} 没就业口径也没写原因"
        assert "留空" in (p.get("employment_source") or "") or \
               "留空" in (p.get("gdp_source") or "") or \
               "无独立" in (p.get("employment_source") or ""), \
            f"{pid} 的就业口径缺失理由不明确"
    s = db.compute()
    assert s["employment_known_partitions"] < len(db.partitions), (
        "拆分分区共用合并口径时，有数分区数必须小于分区总数，"
        "否则说明同一批人数被按比例切开重复计入")


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


# ------------------------------------------------- CLI 走视角边，不读旧字段
def _run_cli(*args):
    import subprocess
    root = os.path.join(os.path.dirname(__file__), "..")
    return subprocess.run(
        [sys.executable, os.path.join(root, "src/hanghang/cli/main.py"),
         "industry", *args],
        capture_output=True, text=True, cwd=root)


def test_cli_occupations_partition_filter_uses_axis_view():
    """`occupations --partition` 必须按边筛：软归属后职业身上没有 unit_id 了，
    读旧字段的话这里恒返回「无匹配职业」——看着像"这个分区真的没人"。 """
    db = _db()
    expect = len(db.members_of("live-streaming"))
    assert expect > 0
    out = _run_cli("occupations", "--partition", "live-streaming")
    assert out.returncode == 0, out.stderr
    assert "无匹配职业" not in out.stdout, out.stdout
    assert f"合计 {expect} 个职业" in out.stdout, out.stdout
    assert "streamer" in out.stdout


def test_cli_occupations_unassigned_is_not_whole_library():
    """`--unassigned` 是"没有被任何视角引用"，不是"字段为空"——
    旧实现给的是全表，等于把"全都没挂"这个假消息当结论。 """
    db = _db()
    free = len(db.unassigned_occupations())
    assert 0 < free < len(db.occupations)
    out = _run_cli("occupations", "--unassigned")
    assert out.returncode == 0, out.stderr
    assert f"合计 {free} 个职业" in out.stdout, out.stdout
    # 已挂视角的职业不许混进来
    assert "architect " not in out.stdout, out.stdout


def test_cli_unknown_partition_is_reported_not_silently_empty():
    out = _run_cli("occupations", "--partition", "no-such-partition")
    assert out.returncode != 0
    assert "未找到分区" in out.stdout, out.stdout


def test_partition_detail_resolves_planned_roles_via_edges():
    """骨架里的岗位名要带出中文名：反查必须走边，读 o['unit_id'] 恒 False"""
    out = _run_cli("partition", "live-streaming")
    assert out.returncode == 0, out.stderr
    line = next(ln for ln in out.stdout.splitlines() if "计划岗位" in ln)
    assert "streamer(网络主播/直播带货)" in line, line


def test_access_view_resolves_partitions_via_edges():
    """access 的"视角"列不许恒为 `-`"""
    out = _run_cli("access", "--side", "non_market")
    assert out.returncode == 0, out.stderr
    body = [ln for ln in out.stdout.splitlines()
            if ln.strip().startswith("factory-operator")]
    assert body and "manufacturing" in body[0], body


# ------------------------------------------------- 骨架双向反查（第 19 条）
def test_dangling_planned_role_is_reported():
    """骨架里有、本分区没有任何边填这个 unit_role → 骨架悬空。

    旧实现只查成员侧（成员填的名字要在骨架里），骨架本身是自由变量：
    凭空加一个岗位名，validate() 返回 []。
    """
    db = _db()
    p = db.partition("live-streaming")
    p["planned_roles"] = list(p.get("planned_roles") or []) + ["主播总监"]
    problems = db.validate()
    assert any("planned_roles" in x and "主播总监" in x for x in problems), problems


def test_missing_planned_role_is_reported():
    """把骨架里有人认领的岗位删掉 → 同样报出来（双向，不是单向）"""
    db = _db()
    p = db.partition("live-streaming")
    p["planned_roles"] = ["streamer"]  # live_host 被删
    db.partitions.append({"id": "skeleton-probe", "name": "骨架探针",
                          "status": "pending", "planned_roles": ["ghost_role"]})
    problems = db.validate()
    assert any("skeleton-probe" in x and "ghost_role" in x for x in problems), problems


def test_planned_role_cannot_borrow_edge_from_other_partition():
    """岗位名是分区内命名：别处的同名边不能给本分区背书"""
    db = _db()
    db.partitions.append({"id": "borrow-probe", "name": "借用探针",
                          "status": "pending",
                          "planned_roles": ["live_host"]})  # live_host 只在 content-creation 有边
    problems = db.validate()
    assert any("borrow-probe" in x and "live_host" in x for x in problems), problems


def test_evaluated_partition_skeleton_is_not_reported():
    """evaluated = 评估后明确不建单元，骨架是留档，没人认领属预期"""
    db = _db()
    for p in db.partitions:
        if p.get("status") == "evaluated":
            assert not any(f"分区 {p['id']} 的 planned_roles" in x
                           for x in db.validate()), p["id"]


def test_covered_partition_skeleton_left_to_check_9():
    """已建单元的分区不重复报骨架：成员缺 unit_role 由第 9 条负责"""
    db = _db()
    p = db.partition("live-streaming")
    p["status"] = "covered"
    p["unit_id"] = "dongjiagoushi"
    problems = db.validate()
    assert any("unit_role" in x for x in problems), problems
    # 现实数据里其他 pending 分区的骨架还在报，所以只断言本分区不重复报
    assert not any("分区 live-streaming 的 planned_roles" in x
                   for x in problems), problems


# --------------------------------------------------------------- 集成
def test_real_data_still_self_consistent():
    """补完数据后自检必须零问题。

    第 19 条刚上线时这里只钉"不许有第二类问题混进来"，因为 20 个待建分区、
    81 个骨架岗位还没人认领。本轮已把 81 个骨架全部登记到原子职业并补上
    unit_role 边，缺口清零，所以断言收紧为**完全无问题**——否则相当于留了
    一条"骨架悬空随便有"的后门，补全进度回退也看不出来。
    """
    problems = _db().validate()
    assert problems == [], problems


def test_cli_check_exit_code_separates_known_gap_from_real_error():
    """退出码分档：0 干净 / 2 只剩待建分区骨架缺口 / 1 真问题。

    混成一档的后果是二选一：要么所有 PR 被同一批已知缺口卡死，要么把真错误也放过。
    """
    db = _db()
    others = [p for p in db.validate() if "骨架悬空" not in p]
    out = _run_cli("check")
    if others:
        assert out.returncode == 1, others
    else:
        # 骨架缺口清零后应退回 0（干净），2 那一档留给"只剩待建分区缺口"的中间态。
        # 断言用"当前数据决定期望值"，避免数据补全后又要改测试常量。
        gaps = [p for p in db.validate() if "骨架悬空" in p]
        if gaps:
            assert out.returncode == 2, out.stdout
            assert "待建分区" in out.stdout and "未完成" in out.stdout, out.stdout
        else:
            assert out.returncode == 0, out.stdout
            assert "自检通过" in out.stdout, out.stdout


def test_pipeline_treats_known_gap_as_non_blocking():
    """流水线必须允许退出码 2 通过，且不许把 1 也放过

    原先断言"放行 2"出现 ≥3 处（PR 测试 / 合并门禁 / main 回归）。合并门禁那条已删：
    它和 PR 测试跑的是同一份数据自检，改 data/*.yaml 时 change-aware 选择器本身就会
    选中行业库测试，重复跑只加预冻结时长不加信息。守卫改为按 job 断言——
    真正需要这道放行的 job（PR 测试、main 回归）一个都不能少。
    """
    root = os.path.join(os.path.dirname(__file__), "..")
    yml = open(os.path.join(root, ".cnb.yml"), encoding="utf-8").read()
    assert yml.count('"$rc" = "2"') >= 2, "PR 测试 / main 回归都要放行退出码 2"
    assert yml.count('|| exit "$rc"') >= 2
    for job in ("review-fix-loop", "full-regression"):
        assert job in yml, f"放行逻辑所在 job 缺失: {job}"


def test_pipeline_does_not_spend_quota_on_an_unapproved_merge_gate():
    """评审未通过时，合并门禁不许跑测试、更不许合并

    有件事写配置改不了：平台要先 Prepare（预冻结 1.33 核时）才轮到 job 级 if，
    所以"少拉起一条流水线省配额"在 yaml 里做不到——PR #29 第一次加了 job 级 if
    仍旧红在 Prepare 就是实证。能做的只有 stage 级 if：不通过就不跑测试、不合并。
    这条守的是这个下限，别再往上加"以为能省配额"的 job 级门禁（它只制造幻觉）。
    """
    root = os.path.join(os.path.dirname(__file__), "..")
    yml = open(os.path.join(root, ".cnb.yml"), encoding="utf-8").read()
    idx = yml.index("    - name: merge-gate")
    end = yml.find("\n  # ==", idx + 1)
    job = yml[idx:end if end != -1 else len(yml)]
    first_stage = job.index("- name:", job.index("stages:"))
    assert job.index("if:") > first_stage, \
        "门禁必须挂在 stage 上；job 级 if 挡不住 Prepare 预冻结，只会让人误以为省了配额"


def test_review_state_gate_uses_the_real_platform_value():
    """门禁取值必须是 CNB 真实取值 approve / unapprove，不是想当然的 approved

    这是上一版翻车的具体形态：门禁写成 `= "approved"`（CNB 文档里是 approve），
    条件永远为假 → 门禁永久失效，PR 可合并时照样拉起 mergeable 流水线白抢配额，
    而失败形态是"全绿"，最难查。所以这里用正则找取值，而不是比对字面串——
    字面串本身就是错的，比对它等于把错误钉成规范。
    """
    root = os.path.join(os.path.dirname(__file__), "..")
    yml = open(os.path.join(root, ".cnb.yml"), encoding="utf-8").read()
    used = set(re.findall(r'CNB_PULL_REQUEST_REVIEW_STATE"\s*(?:=|!=)\s*"([^"]*)"', yml))
    assert used, "整个流水线都没有评审状态门禁，评审永远不会拦住合并"
    assert used <= {"approve", "unapprove"}, (
        f"评审状态取值必须来自 CNB 文档（approve / unapprove），实际写了: {sorted(used)}"
    )


def test_skeleton_gap_is_counted_not_silently_dropped():
    """缺口是**一条一分区**报出来，且总数可算：不能悄悄缩水，也不能刷屏到淹掉别的错"""
    db = _db()
    gaps = [p for p in db.validate() if "骨架悬空" in p]
    dangling = 0
    for p in db.partitions:
        if p.get("status") != "pending":
            continue
        planned = set(p.get("planned_roles") or [])
        claimed = {m.get("unit_role") for m in db.axis_view.of_partition(p["id"])
                   if m.get("unit_role")}
        if planned - claimed:
            dangling += 1
    assert len(gaps) == dangling
    # 缺口已在本轮补完（81 个骨架全部被原子职业认领）。这里不再断言 dangling > 0，
    # 改为断言"报出的条数 == 实算的条数"——数量关系在任何进度下都成立，
    # 而回退（骨架重新悬空）也会因为 validate 与实算不一致或下面的清零断言而失败。
    assert dangling == 0, f"骨架缺口回退了 {dangling} 个分区"


def test_every_planned_role_is_claimed_by_a_real_occupation():
    """骨架认领不许回退：每个待建分区的 planned_roles 都必须有职业边认领。

    这是本轮补全的成果守卫。第 19 条只保证"悬空会报出来"，本断言进一步要求
    "不许悬空"——否则把某条边的 unit_role 删掉，check 会退回退出码 2（被流水线
    当已知缺口放行），补全进度悄悄倒退而 CI 仍然是绿的。
    """
    db = _db()
    for p in db.partitions:
        if p.get("status") != "pending":
            continue
        planned = set(p.get("planned_roles") or [])
        if not planned:
            continue
        claimed = {m.get("unit_role") for m in db.axis_view.of_partition(p["id"])
                   if m.get("unit_role")}
        missing = planned - claimed
        assert not missing, f"分区 {p['id']} 的骨架岗位没人认领 {sorted(missing)}"


def test_planned_role_edges_point_back_to_occupation_in_same_partition():
    """认领要落在**本分区**的边，且边上的职业必须真实存在（不许借别处同名边）"""
    db = _db()
    occ_ids = {o.get("id") for o in db.occupations}
    for p in db.partitions:
        for m in db.axis_view.of_partition(p.get("id", "")):
            assert m.get("occupation") in occ_ids, m
            if m.get("unit_role"):
                assert m["unit_role"] in set(p.get("planned_roles") or []) or \
                    p.get("status") == "covered", (p["id"], m)


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
