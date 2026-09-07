#!/usr/bin/env python3
"""ca-plan 依赖推断内核自校验（防回退护栏）

目的：变更感知选择器自身也是"代码"，若它失效会静默放行缺陷（评审 #26 🟡2）。
本脚本以【固定 fixture 断言】验证依赖推断内核的关键行为不回归：
  改动某核心引擎源码 -> 必须选中直测它的测试（穿透包 __init__ 再导出）。

用法：
  python3 scripts/ca-plan-selfcheck.py
退出码：0 = 全部断言通过；1 = 有断言失败（接入 CI 门禁用）。

注意：需在仓库根目录运行（脚本会 chdir 到仓库根）。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
PLANNER = os.path.join(ROOT, "scripts", "ca-plan.py")

# ---- 从 ca-plan.py 加载"内核层"（到依赖索引主流程之前）----
_source = open(PLANNER, encoding="utf-8").read()
_cut = _source.split("# ---- 依赖索引 ----")[0]
_ns = {}
exec(_cut, _ns)
find_tests = _ns["find_tests"]
covered_files = _ns["covered_files"]

# ---- 建立 src2tests（改动某源码 -> 选中的测试集）----
src2tests = {}
for tf in find_tests():
    for sf in covered_files(tf):
        src2tests.setdefault(sf, set()).add(tf)


def changed_selects(src_file, expect_any_of):
    """改动 src_file 后，选中测试集合必须包含 expect_any_of 中至少一个。"""
    got = src2tests.get(src_file, set())
    missing = set(expect_any_of) - got
    return got, missing


# ---- 固定 fixture 断言（评审 #26 回归护栏）----
CASES = [
    # (改动源码, 必须选中的测试, 说明)
    ("src/hanghang/engine/router.py",
     {"tests/test_router.py"},
     "改 IntentRouter/CompositePlanner 所在 router.py 不得漏直测路由的 test_router"),
    ("src/hanghang/engine/router.py",
     {"tests/test_dongjiagoushi_routing.py"},
     "router.py 改动应命中 dongjiagoushi_routing"),
    ("src/hanghang/engine/registry.py",
     {"tests/test_registry.py"},
     "registry.py 改动不得漏 test_registry"),
    ("src/hanghang/engine/handoff.py",
     {"tests/test_handoff.py"},
     "handoff.py 改动不得漏 test_handoff"),
    ("src/hanghang/engine/prefix.py",
     {"tests/test_dongjiagoushi_routing.py"},
     "prefix.py 改动应命中 dongjiagoushi_routing（经包面再导出）"),
    ("src/hanghang/review/disposition.py",
     {"tests/test_review.py"},
     "独立包 review 改动应精确命中 test_review"),
    ("src/hanghang/context/rules.py",
     {"tests/test_context_m10.py"},
     "context 域改动应命中 test_context_m10"),
    ("src/hanghang/state/arbiter.py",
     {"tests/test_state_arbiter.py"},
     "state 仲裁改动应命中 test_state_arbiter"),
]

fails = 0
for src_file, expect, why in CASES:
    got, missing = changed_selects(src_file, expect)
    if missing:
        fails += 1
        print(f"  ❌ [{src_file}] 缺选中 {sorted(missing)}  {why}")
        print(f"       实际命中: {len(got)} 个 -> {sorted(got)[:6]}...")
    else:
        print(f"  ✅ [{src_file}] 覆盖命中 {sorted(expect)}")

# ---- 汇总 ----
print("-" * 60)
if fails:
    print(f"❌ ca-plan 依赖推断自校验失败：{fails} 项护栏断言未通过")
    print("  提示：改动了 scripts/ca-plan.py 的解析内核，请修复穿透逻辑或更新断言。")
    sys.exit(1)
print("✅ ca-plan 依赖推断内核自校验通过：穿透 __init__ 再导出行为符合护栏。")
sys.exit(0)
