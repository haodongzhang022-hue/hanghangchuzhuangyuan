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

import yaml

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
    旧实现给的是全表，等于把"全都没挂"这个假消息当结论。

    现实数据里 8 个孤立职业已经全部挂上视角（free=0），所以这里**造一个**孤立职业
    来验，而不是依赖"现实里还有人掉队"——否则补全一完成，这条断言就自己失效了。
    """
    db = _db()
    db.occupations.append({"id": "lonely-occ", "name": "谁都没挂的职业",
                           "provider": "human", "billing": "salary"})
    free = len(db.unassigned_occupations())
    assert 0 < free < len(db.occupations), free
    assert "lonely-occ" in {o["id"] for o in db.unassigned_occupations()}
    # CLI 自己读盘，现实数据现已全部有归属 → 必须明确说"无匹配"，
    # 而不是把全表端出来冒充"未挂职业"
    out = _run_cli("occupations", "--unassigned")
    assert out.returncode == 0, out.stderr
    assert "无匹配职业" in out.stdout, out.stdout
    assert "architect " not in out.stdout, out.stdout
    assert len(out.stdout.splitlines()) < 10, out.stdout   # 不是全表


def test_cli_unknown_partition_is_reported_not_silently_empty():
    out = _run_cli("occupations", "--partition", "no-such-partition")
    assert out.returncode != 0
    assert "未找到分区" in out.stdout, out.stdout


def test_partition_detail_resolves_planned_roles_via_edges():
    """骨架里的岗位名要带出中文名：反查必须走边，读 o['unit_id'] 恒 False

    必须挑一个**当前仍是 pending** 的分区来测：已建单元的 CLI 视图不再打印
    「计划岗位」行（骨架已经变成实际 roles），拿它测会 StopIteration。
    真实数据里 pending 可能会被建完，所以这里按状态筛、筛不到就跳过而不是崩。
    """
    from hanghang.engine.industry_db import IndustryDatabase
    pending = [p for p in IndustryDatabase().partitions
               if p.get("status") == "pending"
               and (p.get("planned_roles") or [])]
    if not pending:
        return  # 所有分区都已建单元，这条「骨架反查」的场景不复存在
    pid = pending[0]["id"]
    out = _run_cli("partition", pid)
    assert out.returncode == 0, out.stderr
    lines = [ln for ln in out.stdout.splitlines() if "计划岗位" in ln]
    assert lines, f"{pid} 仍是 pending，应打印计划岗位行:\n{out.stdout[:600]}"
    assert "(" in lines[0], f"计划岗位应带出中文名: {lines[0]}"


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
    """合并只发生在评审通过的那次运行里，别在未评审时白跑一遍合并门禁

    有件事写配置改不了：平台要先 Prepare（预冻结 1.33 核时）才轮到 job 级 if，
    所以"少拉起一条流水线省配额"在 yaml 里做不到。能做的只有 stage 级 if。
    但门禁只挂在 mergeable 上还有第二个问题，比配额更硬（见下一个用例）：
    那个事件读的是目标分支的配置，PR 改流水线时它验证的是旧配置。

    这里守下限：PR 的测试流水线里，合并由同一份 stages 末尾的 git:auto-merge 完成，
    且带 stage 级 if。别再往上加"以为能省配额"的 job 级门禁——它只制造幻觉。
    """
    root = os.path.join(os.path.dirname(__file__), "..")
    yml = open(os.path.join(root, ".cnb.yml"), encoding="utf-8").read()
    idx = yml.index("    - name: review-fix-loop")
    end = yml.find("\n    - name: ", idx + 1)
    job = yml[idx:end if end != -1 else len(yml)]
    assert "type: git:auto-merge" in job, \
        "合并判定要留在 PR 测试流水线里，否则又得多拉一条流水线抢配额"
    merge_at = job.index("type: git:auto-merge")
    gate_at = job.rfind("if:", 0, merge_at)
    assert gate_at != -1, "自动合并必须有评审门禁，不能见绿灯就合"


def test_merge_gate_does_not_run_on_the_target_branch_config():
    """合并门禁不许挂在 pull_request.mergeable 上：那个事件跑的是 main 的旧配置

    官方「代码版本选择」写明 mergeable → 合并前目标分支最新 Commit（配置与工作区
    都是）。PR 里改 .cnb.yml 之后，这条流水线仍在旧配置上跑，于是"修 CI"的 PR
    每次推送都先在旧配置上再红一次，改的人永远看不到自己的修复生效
    （PR #29 连红三轮就是这么来的：每一轮都改了 yaml，每一轮跑的都是上一版）。

    所以合并放到 pull_request.approved：该事件代码与配置都取自预合并，
    且它就是"测试绿 + 评审通过"的最后一个时机。
    """
    root = os.path.join(os.path.dirname(__file__), "..")
    data = yaml.safe_load(open(os.path.join(root, ".cnb.yml"), encoding="utf-8"))
    events = data["$"]
    assert "pull_request.mergeable" not in events, (
        "别配 pull_request.mergeable：它读目标分支的 .cnb.yml，"
        "改流水线的 PR 会被旧配置再红一轮（PR #29 实测）"
    )
    assert "pull_request.approved" in events, \
        "评审通过后必须有一次合并前的完整验证与合并"


def test_approved_event_reuses_the_same_checks_as_pr():
    """评审通过后重跑的那份检查，必须和 PR 时的检查是同一份

    用 YAML 锚点共享，这里钉住"解析后完全相等"。各写一份，改一边忘一边，
    合并前的验证就会悄悄变薄——而它恰好是唯一真正跑在"评审后代码"上的验证。
    """
    root = os.path.join(os.path.dirname(__file__), "..")
    data = yaml.safe_load(open(os.path.join(root, ".cnb.yml"), encoding="utf-8"))
    events = data["$"]
    pr_stages = events["pull_request"][0]["stages"]
    approved_stages = events["pull_request.approved"][0]["stages"]
    assert pr_stages == approved_stages, (
        "pull_request.approved 必须复用 pull_request 的 stages（YAML 锚点 &pr_checks），"
        "各写一份迟早漂移"
    )
    merged = [s for s in approved_stages if s.get("type") == "git:auto-merge"]
    assert merged, "评审通过后那条流水线里必须真的发起合并"
    cond = merged[0].get("if") or ""
    assert "CNB_PULL_REQUEST_REVIEW_STATE" in cond and "approve" in cond, cond
    # 光看评审状态不够：测试判定也必须跨 stage 传过来，否则"测试没过也合并"
    assert "MERGE_PENDING" in cond, (
        "合并条件必须同时认测试判定（MERGE_PENDING），否则测试失败也会合并")


def test_merge_decision_crosses_stage_boundary_through_an_export():
    """判定必须经 exports 过 stage：shell 变量出不了 script 子进程

    这个坑的形态是"全绿但永不合并"——变量在下个 stage 里根本不存在，
    条件恒假，而流水线状态正常。所以这里钉住两件事：那个 stage 有 exports，
    且 exports 里真的把 MERGE_PENDING 导了出去。
    """
    root = os.path.join(os.path.dirname(__file__), "..")
    data = yaml.safe_load(open(os.path.join(root, ".cnb.yml"), encoding="utf-8"))
    stages = data["$"]["pull_request"][0]["stages"]
    holders = [s for s in stages if "MERGE_PENDING" in (s.get("script") or "")]
    assert holders, "没有任何 stage 计算 MERGE_PENDING，合并条件会恒假"
    exported = []
    for s in holders:
        exported += list((s.get("exports") or {}).values())
    assert "MERGE_PENDING" in exported, (
        "MERGE_PENDING 必须以 CNB 的 ##[set-output] 输出并由 exports 带出 stage，"
        "否则下个 stage 读不到它")
    # 输出协议必须是 CNB 的 ##[set-output]：只赋值 shell 变量等于没传
    assert "##[set-output merge=" in holders[0]["script"], (
        "变量要以 ##[set-output key=value] 输出，只写 shell 变量传不出 stage")
    # 导出链路坏了要显式报错，不能"条件恒假 + 全绿"
    consumers = [s for s in stages
                 if "MERGE_PENDING" in (s.get("script") or "")
                 and s is not holders[0]]
    assert consumers, "没有 stage 消费 MERGE_PENDING"
    assert any("MERGE_PENDING" in (c.get("script") or "")
               and "-z" in (c.get("script") or "") for c in consumers), (
        "消费端必须对空值显式报错：导出链路坏了的时候，合并条件恒假但流水线全绿")
    # $GITHUB_OUTPUT 是 GitHub Actions 的文件约定，CNB 没有这个文件：
    # 写成它 → 条件恒假 → 导出空串 → 合并门禁永久失效且流水线全绿。
    assert "GITHUB_OUTPUT" not in holders[0]["script"], (
        "$GITHUB_OUTPUT 在 CNB 不存在，会导致合并门禁静默失效")


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


def test_every_pipeline_declares_its_own_runner_size():
    """每条流水线都要显式写 runner.cpus：不写不是"用最小规格"，是 8 核。

    这不是风格问题，是额度问题。PR #34 的 CI 连红在 Prepare，报的正是
    `insufficient for pre-freezing(1.33 core-hours)` —— 1.33 = 8 核 × 10min，
    也就是「没写 runner.cpus」时平台给的默认节点规格。原 .cnb.yml 注释把它读成
    「1 核 × 1/3 小时」，据此断定「与申请几核无关，只能等根组织提额度」，
    于是这一整块配置长期没人动，最贵的默认规格落在最该跑的那几条上。

    实测（同一组织、同一时刻，api_trigger 单变量对照）：
      8 核 → error 1.33 核时 / 4 核 → error / 3 核 → error
      2 核 → success / 1 核 → success
    冻结量随核数线性收缩，所以「配置层没有替代品」是错的。

    这里守的是别退回去：删掉这行想"简化配置"，省下的一行会在下次额度见底时
    变成 Prepare 报错，而那时没人会想到是它。上限 2 核同样是实测结果——
    这些 job 是串行 python 测试与 AI 接口等待，吃不满多核，多给的核只烧额度。
    """
    root = os.path.join(os.path.dirname(__file__), "..")
    data = yaml.safe_load(open(os.path.join(root, ".cnb.yml"), encoding="utf-8"))

    def pipelines(node):
        """递归取出所有 Pipeline（分支 → 事件 → 列表，值都是 dict）。"""
        if isinstance(node, list):
            for x in node:
                yield from pipelines(x)
        elif isinstance(node, dict):
            if "stages" in node:
                yield node
            else:
                for v in node.values():
                    yield from pipelines(v)

    missing, too_big = [], []
    for pipe in pipelines(data):
        cpus = (pipe.get("runner") or {}).get("cpus")
        if not cpus:
            missing.append(pipe.get("name"))
        elif cpus > 1:
            too_big.append(f"{pipe.get('name')}={cpus}")
    assert not missing, (
        "这些流水线没写 runner.cpus，会静默跑在 8 核默认节点上"
        f"（每次预冻结 1.33 核时，额度一紧就 Prepare 红）：{missing}")
    assert not too_big, (
        f"这些流水线申请的核数超过 1 核：本仓库所有 job 都是串行 python 测试"
        f"或等在 AI 接口上（实测全量 37 个测试文件单进程 470s，多核用不上），"
        f"多出来的核不被使用却按节点规格计入冻结量，纯烧额度：{too_big}")


def test_no_pipeline_defines_a_roleless_ok_stage():
    """没职责的 stage 一个都不留：它可以被删掉而流水线行为完全不变，那就该删。

    上一版留了一个 endStages：专门在"评审未通过"时打一行日志，靠 allowFailure
    保证不标红。查语法手册核对后发现它一层职责都担不了——
      - 语法手册 endStages：prepare 成功后必执行，且**是否成功不影响流水线状态**，
        所以那条 allowFailure 是空转；
      - CNB_PULL_REQUEST_REVIEW_STATE 是 approve/unapprove，根本没发生过"评审未通过
        就标红"这回事，它想遮的问题不存在；
      - 真正的失败发生在 Prepare（配额见底），而 prepare 失败时 endStages 不执行。
    它只是"又一次试图用配置压掉红叉"的残留。这条断言要求 stages / endStages /
    failStages 里每个任务都担着实质职责，别再往里加纯装饰。
    """
    root = os.path.join(os.path.dirname(__file__), "..")
    data = yaml.safe_load(open(os.path.join(root, ".cnb.yml"), encoding="utf-8"))

    def pipelines(node):
        """递归取出所有 Pipeline（分支 → 事件 → 列表，值都是 dict）。"""
        if isinstance(node, list):
            for x in node:
                yield from pipelines(x)
        elif isinstance(node, dict):
            # Pipeline 的特征是有 stages；事件/分支层的 dict 没有 stages，继续下钻。
            if "stages" in node:
                yield node
            else:
                for v in node.values():
                    yield from pipelines(v)

    allowed_script_prefixes = ("echo",)  # 只读日志、不承担职责的 script 一律不该存在
    for pipe in pipelines(data):
        for key in ("endStages", "failStages"):
            assert key not in pipe, (
                f"流水线 {pipe['name']} 又加了 {key}：无职责的收尾任务删掉即可，"
                "别用 allowFailure 假装它在起作用"
            )
        for stage in pipe["stages"]:
            if stage.get("type"):
                continue  # 内置任务自有语义，不在此处判断
            body = (stage.get("script") or "").strip()
            first = body.splitlines()[0].strip() if body else ""
            assert body and not first.startswith(allowed_script_prefixes), (
                f"stage {stage.get('name')} 的 script 只有日志、没有职责："
                "删掉它，或让它真的承担一件事"
            )


def test_pipeline_prompts_never_summon_bare_codebuddy():
    """流水线自己的提示词里不许写裸 `@CodeBuddy`：那是另一套配置，也是另一份配额

    `.cnb.yml` 里声明的 `runner.cpus` 只管**本仓库配置的流水线**。裸 `@CodeBuddy`
    命中的是平台系统 NPC，它按系统默认配置起机器——本仓库管不到，实际是 8 核。

    实测（本仓库历史构建，按标题区分两种召唤形式，同一条 PR 流水线）：
      裸 `@CodeBuddy`        144 次 / 268.3 核时
      全限定 `@repo(CodeBuddy)` 72 次 /  27.0 核时
    同样的事，差 10 倍。2026-11-15 那次 CI 连红在 Prepare，报
    `insufficient for pre-freezing`：本月已用 274.6 核时，而免费额度是 160 核时/月
    —— 缺口的大头就是这么烧掉的。

    除了配额，裸名还绕过本仓库提示词里写死的边界（评审员只读、修复者禁止 push、
    空修复检测、二选一纪律都不在那个系统提示词里）。所以这里守两件事：
    提示词不许出现裸名；出现召唤就必须是全限定名。
    """
    root = os.path.join(os.path.dirname(__file__), "..")
    data = yaml.safe_load(open(os.path.join(root, ".cnb.yml"), encoding="utf-8"))
    qualified = "@dongdongxiaozu/hanghangchuzhuangyuan(CodeBuddy)"

    def pipelines(node):
        if isinstance(node, list):
            for x in node:
                yield from pipelines(x)
        elif isinstance(node, dict):
            if "stages" in node:
                yield node
            else:
                for v in node.values():
                    yield from pipelines(v)

    bare = []
    for pipe in pipelines(data):
        for stage in pipe["stages"]:
            opts = stage.get("options") or {}
            prompt = f"{opts.get('systemPrompt') or ''}{opts.get('userPrompt') or ''}"
            # 全限定名本身含 "CodeBuddy"，先剔掉再找残留的裸名。
            rest = prompt.replace(qualified, "")
            hits = [m for m in re.findall(r"@[\w\-./]*CodeBuddy\w*", rest) if m == "@CodeBuddy"]
            if hits:
                bare.append(f"{pipe.get('name')} / {stage.get('name')}")
    assert not bare, (
        "这些流水线的提示词在教 NPC 写裸 `@CodeBuddy`：裸名命中的是平台系统 NPC，"
        "不读本仓库 .cnb.yml（跑 8 核默认规格，实测核时差 10 倍），也不受本仓库"
        f"提示词里的权限边界约束。改成全限定名 {qualified}：{bare}"
    )


def test_npc_role_prompts_carry_the_same_discipline():
    """真正生效的那份提示词必须带同样的纪律：`.cnb/settings.yml` 的 NPC 角色

    这条是上一条的补丁。上一条断言（以及再上一条）查的都是 `.cnb.yml` 里
    `npc:go.options` 的提示词 —— 而官方文档「提示词配置」写明：

      `@NPC` 评论触发时，平台按 `.cnb/settings.yml` 的角色定义注入提示词，
      `.cnb.yml` 里 options 的 systemPrompt / userPrompt / role **即使配了也会被忽略**。

    也就是说，真人或评审 NPC 一召唤，跑的是 settings.yml 那段 prompt。
    前几轮把「只准写全限定名」「召唤与打回二选一」写在了 `.cnb.yml` 里，
    于是在真正触发的那条路上，一条都不生效 —— 而断言还一直是绿的。

    **断言写在错的文件上，与没有断言是同一种下场**，只是多了个绿灯。

    实测（本仓库 PR #34 的 comment@npc 会话，按召唤形式分组）：
      裸名召唤        9 次 / 58.9 核时  ← 命中平台系统 NPC，8 核默认规格
      全限定名召唤    1 次 /  2.4 核时
    """
    root = os.path.join(os.path.dirname(__file__), "..")
    data = yaml.safe_load(open(os.path.join(root, ".cnb", "settings.yml"), encoding="utf-8"))
    prompts = {r["name"]: r.get("prompt") or "" for r in data["npc"]["roles"]}
    qualified = "@dongdongxiaozu/hanghangchuzhuangyuan(CodeBuddy)"

    # ① 角色提示词里不许教人裸写（先剔全限定名，再找残留的裸名）
    bare = []
    for name, prompt in prompts.items():
        rest = prompt.replace(qualified, "")
        if re.search(r"(?<![\w/])@CodeBuddy\b", rest):
            bare.append(name)
    assert not bare, (
        f"这些 NPC 角色提示词在教人裸写 @CodeBuddy：裸名命中平台系统 NPC，"
        f"不读本仓库 .cnb.yml（8 核默认规格，实测同量级工作差 10~25 倍核时），"
        f"也不受本文件任何边界约束。改成全限定名 {qualified}：{bare}"
    )

    # ② 审查员：二选一 + 配额类红灯不召唤 都必须在生效的提示词里
    review = prompts.get("代码审查员") or ""
    assert "二选一" in review, "审查员提示词必须写明「召唤」与「打回」二选一"
    assert "changes_requested" in review, "审查员提示词要写出打回的事件名，否则无从判断"
    assert "Prepare" in review and "insufficient" in review, (
        "审查员提示词必须写明：失败 Stage 是 Prepare / 报错含 insufficient 时"
        "属配额见底，不许召唤修复 —— 这类红灯不在代码里，召唤只会空转一小时再回一句"
        "「跟代码无关」，实测每小时 8 核时"
    )

    # ③ 修复者：先判断红灯归谁，不空转
    fixer = prompts.get("CodeBuddy") or ""
    for token in ("Prepare", "core-hours", "不读代码"):
        assert token in fixer, (
            f"CodeBuddy 角色提示词缺少「先判断红灯归谁」的关键约束：{token}。"
            "缺了它，配额见底时修复 Agent 会照常读代码、跑全量测试、"
            "再回一句「跟代码无关」"
        )
    assert "全限定名" in fixer, "修复者提示词必须写明召唤只写全限定名"


def test_npc_fix_channels_share_one_lock():
    """两条修复通道共用一把锁：同一 PR 同一时刻只能有一条修复会话

    `pull_request.changes_requested`（兜底）与 `pull_request.comment@npc`（主通道）
    做的是同一件事。提示词里写的「二选一」是自觉，lock 是机制——
    自觉会忘，机制不会。实测 29 次打回里 22 次与召唤会话同一分钟起跑，
    11 月这条通道烧掉 80.1 核时，几乎全是重复。

    锁的 key 必须带 PR 编号：不带就会跨 PR 串行，等于把并行评审也一起关掉。
    """
    root = os.path.join(os.path.dirname(__file__), "..")
    data = yaml.safe_load(open(os.path.join(root, ".cnb.yml"), encoding="utf-8"))

    def pipeline(event, name):
        return next(j for j in data["$"][event] if j.get("name") == name)

    auto_fix = pipeline("pull_request.changes_requested", "auto-fix")
    invoke = pipeline("pull_request.comment@npc", "npc-manual-invoke")

    keys = []
    for job in (auto_fix, invoke):
        lock = job.get("lock") or {}
        assert lock.get("cancel-in-progress") is True, (
            f"{job['name']} 没配 cancel-in-progress：后到的会话会排队等锁，"
            "而不是取消前一条 —— 排队期间它照样占着预冻结额度"
        )
        keys.append(lock.get("key"))
    assert keys[0] == keys[1], (
        f"两条修复通道要共用一把锁，现在分别是 {keys[0]} / {keys[1]}："
        "不共用的锁只挡自己，挡不住另一条通道"
    )
    assert "CNB_PULL_REQUEST_IID" in (keys[0] or ""), (
        f"锁 key 必须带 PR 编号（现在 {keys[0]}）：不带就会跨 PR 串行，"
        "把所有 PR 的评审排队成一条"
    )


def test_pr_review_pipelines_stop_when_the_branch_moves_on():
    """源分支一更新，对着旧 commit 的测试与评审就该终止，而不是跑完再贴过期结论

    官方 `breakIfModify`：Job 执行前若源分支已更新，则终止构建。

    为什么这条值钱：`npc-code-review` 是本仓最慢的一条（实测单次 27~88 分钟，
    时间全花在等模型上），`review-fix-loop` 跑全量测试要 8 分钟。这两条评的都是
    **某个具体 commit**。分支一更新，那个 commit 就已被取代 —— 结论没人会看，
    但机器早就按节点规格冻结过额度了。

    `merge-on-approve` 刻意不在这条里：它跑在合并前的最后一刻，终止它等于让合并
    永远等不到绿灯；它由本 PR 自己的 `stages` 保证只跑一次。
    """
    root = os.path.join(os.path.dirname(__file__), "..")
    data = yaml.safe_load(open(os.path.join(root, ".cnb.yml"), encoding="utf-8"))

    missing = [j["name"] for j in data["$"]["pull_request"]
               if j.get("breakIfModify") is not True]
    assert not missing, (
        f"这些 pull_request 流水线没配 breakIfModify：源分支更新后它们仍在对着"
        f"已被取代的 commit 跑，结论过期而额度照烧：{missing}"
    )


def test_review_prompt_forbids_double_dispatch():
    """评审员不许既召唤修复又打回：那是两条并行会话改同一批代码

    主通道是评审结论里召唤 `pull_request.comment@npc`，`pull_request.changes_requested`
    只是兜底。两条同时开火时，两个修复 Agent 会在同一个分支上改同一批文件。

    实测本仓库历史：29 次 `changes_requested` 里 22 次都与一条 `@CodeBuddy` 会话在
    同一分钟内起跑（间隔 ≤3 min），11 月这条通道烧掉 80.1 核时，几乎全是重复。

    这里守提示词里那句纪律还在：它不是文档，是让两条通道不并发的唯一机制。
    """
    root = os.path.join(os.path.dirname(__file__), "..")
    data = yaml.safe_load(open(os.path.join(root, ".cnb.yml"), encoding="utf-8"))

    review_job = next(j for j in data["$"]["pull_request"] if j.get("name") == "npc-code-review")
    prompt = (review_job["stages"][0].get("options") or {}).get("userPrompt") or ""

    assert "二选一" in prompt, (
        "评审提示词必须写明「召唤修复」与「提交打回」只能二选一，"
        "否则两条通道会各自拉起一个修复 Agent 改同一批代码"
    )
    for token in ("changes_requested", "不要"):
        assert token in prompt, f"评审提示词缺少约束：{token}"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ✅ {name}")
    print("✅ 行业补全与视角分离测试通过")
