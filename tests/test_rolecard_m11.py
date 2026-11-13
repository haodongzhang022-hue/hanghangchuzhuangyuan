"""M11 岗位画像层测试

覆盖：
  1. 数据契约与渲染（profile → rolecard，六维齐全 / 就绪度评级）
  2. 缺画像的岗位优雅降级（打分如实扣分 + 缺口清单，不抛异常）
  3. 工作流模板合并（岗位只覆盖要改的步骤，模板新增步骤能继承）
  4. M1 路由激活加权（数据驱动，且不影响未写画像的单元）
  5. M10 上下文注入（岗位卡进层A，缓存键仅由画像数据决定、跨会话稳定）
  6. CLI role 子命令（list/show/playbook/context/coverage 冒烟）
"""
from __future__ import annotations

import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../src"))

from hanghang.context import ContextAssembler  # noqa: E402
from hanghang.engine import IntentRouter, Registry  # noqa: E402
from hanghang.rolecard import RoleCardStore, WorkflowRenderer  # noqa: E402
from hanghang.rolecard.workflow import deep_merge  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(REPO, "src", "hanghang", "cli", "main.py")


def _store() -> RoleCardStore:
    return RoleCardStore(registry=Registry())


# ---------------------------------------------------------------- 1. 渲染
def test_render_full_profile():
    store = _store()
    card = store.get("dongjiagoushi", "architect")
    assert card is not None
    assert card.prefix == "[架构]"
    # 六维齐全
    p = card.profile
    assert p.analysis.get("mission")
    assert p.persona.get("tone")
    assert p.plugin.get("bundle")
    assert p.stakeholders.downstream
    assert p.capability.average_score() > 0
    # 工作流渲染出步骤
    steps = card.playbook()
    assert len(steps) >= 5
    assert all(s.runtime in ("agent", "n8n", "code") for s in steps)
    # 就绪度评级
    assert card.readiness.score >= 75
    assert card.readiness.grade == "A"
    print("  ✅ test_render_full_profile")


def test_render_degrades_without_profile():
    """没有画像基线时：卡仍可生成（路由/前缀可用），但就绪度如实为 D 并登记缺口。"""
    store = _store()
    store.profiles.pop("dongjiagoushi", None)
    card = store.get("dongjiagoushi", "developer")
    assert card.profile is None
    assert card.keywords  # 注册表事实仍在
    assert card.readiness.grade == "D"
    assert any("画像基线" in g for g in card.readiness.gaps)
    print("  ✅ test_render_degrades_without_profile")


def test_readiness_scoring_shapes():
    """评分口径：六维未填 → 扣 six_dims；能力未评 → 扣 capability，且都给得出缺口。"""
    store = _store()
    card = store.get("dongjiagoushi", "secretary")
    assert card.readiness.factors["six_dims"] == 1.0
    store.profiles["dongjiagoushi"]["secretary"].capability.scoring = {}
    store._cards.clear()
    card2 = store.get("dongjiagoushi", "secretary")
    assert card2.readiness.factors["capability"] == 0.0
    assert card2.readiness.score < card.readiness.score
    assert any("capability.scoring" in g for g in card2.readiness.gaps)
    print("  ✅ test_readiness_scoring_shapes")


# ---------------------------------------------------------------- 2. 模板合并
def test_workflow_step_merge_by_id():
    base = {"steps": [{"id": "a", "name": "A", "verify": ["x"]},
                      {"id": "b", "name": "B"}]}
    merged = deep_merge(base, {"steps": {"a": {"name": "AA"}}})
    ids = [s["id"] for s in merged["steps"]]
    assert ids == ["a", "b"]          # 模板步骤不丢
    assert merged["steps"][0]["name"] == "AA"
    assert merged["steps"][0]["verify"] == ["x"]  # 未覆盖字段保留
    print("  ✅ test_workflow_step_merge_by_id")


def test_renderer_falls_back_to_min_flow():
    renderer = WorkflowRenderer({})
    wf = renderer.render({"template": "不存在的模板", "id": "wf-x"}, "developer")
    assert wf and wf["steps"], "模板缺失应降级到 min-flow 而不是空流程"
    print("  ✅ test_renderer_falls_back_to_min_flow")


def test_playbook_export_formats():
    store = _store()
    card = store.get("finance-accounting", "accountant")
    steps = card.playbook()
    assert steps
    r = subprocess.run([sys.executable, CLI, "role", "playbook", "accountant",
                        "--format", "n8n"], capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0 and "nodes:" in r.stdout
    r2 = subprocess.run([sys.executable, CLI, "role", "playbook", "accountant",
                         "--format", "code"], capture_output=True, text=True, cwd=REPO)
    assert r2.returncode == 0 and "STEPS = [" in r2.stdout
    print("  ✅ test_playbook_export_formats")


# ---------------------------------------------------------------- 3. 路由加权
def test_activation_weight_affects_routing():
    """画像 activation.weight > 1 让该岗位在行业评分中更早胜出。"""
    reg = Registry()
    store = RoleCardStore(registry=reg)
    router = IntentRouter(reg, rolecard_store=store)
    assert router._activation_weight("dongjiagoushi", "architect") >= 1.0

    store.profiles["dongjiagoushi"]["architect"].workflow["activation"] = {"weight": 2.0}
    store._cards.clear()
    router2 = IntentRouter(reg, rolecard_store=store)
    assert router2._activation_weight("dongjiagoushi", "architect") == 2.0

    # 加权后「架构」信号更重，路由仍落在架构岗
    result = router2.route("帮我做架构设计")
    assert result.unit_id == "dongjiagoushi"
    assert "architect" in result.roles
    print("  ✅ test_activation_weight_affects_routing")


def test_routing_unchanged_without_rolecard_store():
    """不注入画像层时路由结果与接入前一致（向后兼容）。"""
    reg = Registry()
    plain = IntentRouter(reg)
    weighted = IntentRouter(reg, rolecard_store=RoleCardStore(registry=reg))
    for text in ["帮我做架构方案", "审一下劳动合同", "帮我算这个月工资", "做个游戏关卡"]:
        a, b = plain.route(text), weighted.route(text)
        assert a.unit_id == b.unit_id, f"{text}: {a.unit_id} != {b.unit_id}"
        assert a.roles == b.roles, f"{text}: {a.roles} != {b.roles}"
    print("  ✅ test_routing_unchanged_without_rolecard_store")


# ---------------------------------------------------------------- 4. 上下文注入
def test_rolecard_injected_into_layer_a_and_cache_stable():
    store = _store()
    provider = lambda u, r: store.get(u, r).to_context_block()
    asm = ContextAssembler(rolecard_provider=provider)

    a = asm.assemble(session_id="s1", unit_id="data-analytics",
                     role_name="data_analyst", static_prefix="[数分]")
    b = asm.assemble(session_id="s2", unit_id="data-analytics",
                     role_name="data_analyst", static_prefix="[数分]")
    assert "岗位卡: data_analyst" in a["layer_a"]
    assert "口径" in a["layer_a"]
    # 缓存键只由层A决定：不同会话、同岗位 → 同一缓存键
    assert a["cache_key"] == b["cache_key"]

    plain = ContextAssembler().assemble(session_id="s3", unit_id="data-analytics",
                                        role_name="data_analyst", static_prefix="[数分]")
    assert plain["cache_key"] != a["cache_key"], "注入岗位卡后层A内容应变，缓存键随之变化"
    print("  ✅ test_rolecard_injected_into_layer_a_and_cache_stable")


def test_rolecard_provider_failure_is_isolated():
    """画像层异常不得影响装配主链路。"""
    def boom(u, r):
        raise RuntimeError("画像炸了")

    out = ContextAssembler(rolecard_provider=boom).assemble(
        session_id="s", unit_id="dongjiagoushi", role_name="developer",
        static_prefix="[开发]")
    assert out["layer_a"]
    assert "session_context_static=true" in out["layer_a"]
    print("  ✅ test_rolecard_provider_failure_is_isolated")


# ---------------------------------------------------------------- 5. CLI 冒烟
def test_cli_role_commands():
    for args, expect in [
        (["role", "list"], "就绪度"),
        (["role", "show", "architect", "--unit", "dongjiagoushi"], "① 岗位分析"),
        (["role", "playbook", "architect", "--unit", "dongjiagoushi"], "做法:"),
        (["role", "context", "architect", "--unit", "dongjiagoushi"], "岗位卡"),
        (["role", "coverage"], "M11 岗位画像覆盖"),
    ]:
        r = subprocess.run([sys.executable, CLI] + args, capture_output=True,
                           text=True, cwd=REPO)
        assert r.returncode == 0, f"{args} 退出码 {r.returncode}: {r.stderr[:300]}"
        assert expect in r.stdout, f"{args} 输出缺少 {expect}"
    print("  ✅ test_cli_role_commands")


def test_all_registered_roles_have_profiles():
    """全部注册岗位都有画像基线（缺了就在覆盖率里暴露，避免悄悄降级）。"""
    store = _store()
    summary = store.coverage_summary()
    assert summary["total_roles"] > 0
    assert summary["profile_coverage"] == 1.0, (
        f"岗位画像覆盖不足: {summary}")
    print("  ✅ test_all_registered_roles_have_profiles")


def test_readiness_fields_follow_schema():
    """六维口径必须等于 schema 声明的字段：代码不许持有第二份清单。

    清单抄在代码里会漂（曾经 19 个字段 vs schema 29 个），漂了之后漏填字段
    不扣分、不登记缺口，就绪度全 A 也不可信。守分母，不守分数。
    """
    import copy

    import yaml

    store = _store()
    with open(os.path.join(REPO, "data", "rolecard-schema.yaml"), encoding="utf-8") as fh:
        schema = yaml.safe_load(fh)
    want = {dim: list(spec["fields"]) for dim, spec in schema["dimensions"].items()}
    got = {dim: list(names) for dim, names in store.scorer.dimension_fields.items()
           if dim in want}
    assert got == want, f"六维字段与 schema 不一致：{got} != {want}"

    # 每个 schema 字段被置空都要真的扣分并登记缺口
    for dim, fields in want.items():
        for f in fields:
            card = copy.deepcopy(store.get("dongjiagoushi", "architect"))
            holder = card.profile.dimension(dim)
            if isinstance(holder, dict):
                holder.pop(f, None)
            else:
                setattr(holder, f, None if f == "scoring" else [])
            if dim == "workflow" and f == "handoff_out":
                # 交接约定由工序模板继承，清画像字段没用：把它从渲染后的工序上摘掉
                for wf in card.workflows:
                    wf["handoff_out"] = ""
            gaps = []
            score = store.scorer.six_dim_score(card, gaps)
            assert score < 1.0, f"{dim}.{f} 置空却仍满分"
            assert f"{dim}.{f} 未填" in gaps, f"{dim}.{f} 未登记缺口：{gaps}"


def test_readiness_counts_incentives():
    """利益链条清晰度要数 incentives：它有独立数据，漏掉就是白写。"""
    import copy

    store = _store()
    card = copy.deepcopy(store.get("dongjiagoushi", "architect"))
    before = store.scorer.beneficiary_score(card, [])
    card.profile.stakeholders.incentives = []
    after = store.scorer.beneficiary_score(card, [])
    assert after < before, f"incentives 清空后分数没变：{before} → {after}"


def test_coverage_summary_follows_filter():
    """汇总必须与眼前列出的行同口径：传 cards 就只统计这批。

    否则 `role list --unit X` 会列出 4 行、汇总却打全库 51 个岗位。
    """
    store = _store()
    cards = [c for c in store.all_cards() if c.unit_id == "content-creation"]
    part = store.coverage_summary(cards)
    full = store.coverage_summary()
    assert part["total_roles"] == len(cards) < full["total_roles"], (part, full)
    assert part["profiled_roles"] <= part["total_roles"]
    assert sum(part["grades"].values()) == len(cards)
    print("  ✅ test_coverage_summary_follows_filter")


def test_generated_rolecards_in_sync():
    """data/rolecards 已提交产物必须与当前数据一致（防止改画像忘重渲）。"""
    r = subprocess.run([sys.executable,
                        os.path.join(REPO, "scripts", "gen_rolecards.py"),
                        "--check", "--quiet"], capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0, f"岗位卡过期，请重跑 gen_rolecards.py:\n{r.stderr}"
    print("  ✅ test_generated_rolecards_in_sync")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"  ❌ {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  ❌ {t.__name__}: {type(e).__name__}: {e}")
    print("✅ M11 岗位画像层测试全部通过" if not failed else f"❌ {failed} 个测试失败")
    raise SystemExit(1 if failed else 0)
