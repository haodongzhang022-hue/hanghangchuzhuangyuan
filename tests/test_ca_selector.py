#!/usr/bin/env python3
"""变更感知测试选择器 回归守卫（评审 #26 · tests/test_ca_selector.py）

护栏目的：
  变更感知选择器（scripts/ca-plan.py）决定 CI/门禁会跑哪些回归测试，若其选择逻辑
  失效会"漏测 / 假绿"：改路由数据却 0 测试、改核心引擎却漏跑直测文件。
  本文件以【自包含临时 git 仓库 fixture】端到端跑真实 ca-plan.py 内核，固化两条
  护栏断言，防止回退：
    C-1 改动经包 __init__ 再导出的核心源码（src/.../router.py）
        -> 必须选中直测它的 test_router（穿透 __init__ 后不落空）；
    C-2 改动行为数据路由文件（data/*.yaml）
        -> 绝不 0 选中（假绿），必须路由到数据驱动回归全量兜底。

用法：python3 tests/test_ca_selector.py   （仓库根运行或任意，内部 chdir）
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLANNER = os.path.join(ROOT, "scripts", "ca-plan.py")


def run(cmd, cwd):
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)


def write(p, content):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(content)


def commit(d, msg):
    """在 fixture 仓库提交（关闭 gpg 签名，避免 CI/本地全局 gpgsign 干扰）。"""
    r = run(["git", "-c", "commit.gpgsign=false",
             "-c", "user.email=ca-sel@test", "-c", "user.name=ca-sel",
             "commit", "-qm", msg], d)
    if r.returncode != 0:
        raise RuntimeError("fixture commit failed: " + r.stderr)
    return r


def build_fixture():
    """构造自包含临时 git 仓库，含可被穿透解析的包源码 + 数据路由文件。"""
    d = tempfile.mkdtemp(prefix="ca-sel-")
    write(os.path.join(d, "src/hanghang/__init__.py"), "")
    # 包 __init__ 通过相对再导出聚合 router（模拟本仓 hanghang.engine 形态）
    write(os.path.join(d, "src/hanghang/engine/__init__.py"),
          "from .router import Router\n")
    write(os.path.join(d, "src/hanghang/engine/router.py"),
          "class Router:\n    pass\n")
    # 测试：走包面 import（需穿透 __init__ 落到 router.py）
    write(os.path.join(d, "tests/__init__.py"), "")
    write(os.path.join(d, "tests/test_router.py"),
          "from hanghang.engine import Router\n"
          "def test_router():\n    assert Router\n")
    # 独立数据驱动测试（不与 router 关联）
    write(os.path.join(d, "tests/test_data_driven.py"),
          "def test_data():\n    assert True\n")
    # 纯文档（非触发）
    write(os.path.join(d, "README.md"), "# demo\n")
    # 行为路由数据文件
    write(os.path.join(d, "data/industry-register.yaml"),
          "industries:\n  - dongjiagoushi\n")
    run(["git", "init", "-q"], d)
    run(["git", "add", "-A"], d)
    commit(d, "base")
    base = run(["git", "rev-parse", "HEAD"], d).stdout.strip()
    return d, base


def select_on_change(d, base, changed_rel, content):
    """从 base 干净态仅改一个文件(新提交)后跑真实内核，返回选中测试集合。"""
    # 重置回 base，保证每次场景仅改动 changed_rel 一个文件（互不叠加）
    run(["git", "reset", "-q", "--hard", base], d)
    run(["git", "clean", "-qfd"], d)
    path = os.path.join(d, changed_rel)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(content)
    run(["git", "add", "-A"], d)
    commit(d, "change")
    r = run([sys.executable, PLANNER, f"--base={base}", "--src=src/"], d)
    if r.returncode != 0:
        return None, r.stderr
    return {row[0] for row in json.loads(r.stdout)}, r.stderr


def main():
    d, base = build_fixture()
    try:
        # ---- C-1：改核心源码(经 __init__ 再导出) -> 必选直测它的 test_router ----
        sel, err = select_on_change(
            d, base, "src/hanghang/engine/router.py", "\n# touch\n")
        if sel is None:
            print(f"❌ [C-1] ca-plan 内核运行失败: {err}")
            return 1
        expect_router = {"tests/test_router.py"}
        if not (sel & expect_router):
            print("❌ [C-1] 改 router.py 未选中 test_router（穿透 __init__ 失效/漏选）")
            print(f"       选中: {sorted(sel)}")
            return 1
        print("✅ [C-1] 改经 __init__ 再导出的 router.py → 命中 test_router")

        # ---- C-2：改行为数据路由文件 -> 绝不 0 选中（假绿），必路由数据驱动全量 ----
        sel2, err2 = select_on_change(
            d, base, "data/industry-register.yaml", "\n  - legal\n")
        if sel2 is None:
            print(f"❌ [C-2] ca-plan 内核运行失败: {err2}")
            return 1
        if not sel2:
            print("❌ [C-2] 改 data/industry-register.yaml 选中 0 测试（门禁假绿）")
            return 1
        need_data = {"tests/test_data_driven.py"}
        if not (sel2 & need_data):
            print("❌ [C-2] 改行为数据未命中数据驱动测试（应路由到数据驱动回归）")
            print(f"       选中: {sorted(sel2)}")
            return 1
        print("✅ [C-2] 改 data/*.yaml 行为数据 → 命中数据驱动回归，非 0 选中")

        # ---- 纯文档变更 -> 应为空（不误触发）----
        sel3, err3 = select_on_change(
            d, base, "README.md", "\ndoc\n")
        if sel3 is None:
            print(f"❌ [doc] ca-plan 内核运行失败: {err3}")
            return 1
        if sel3:
            print("❌ [doc] 纯文档变更却触发了行为测试")
            return 1
        print("✅ [doc] 纯文档变更 → 空选中（不误触发）")
    finally:
        run(["rm", "-rf", d], "/tmp")

    print("-" * 60)
    print("✅ tests/test_ca_selector.py 回归守卫全部通过：")
    print("   ① 源码经 __init__ 再导出不漏测 ② 行为数据变更不假绿 ③ 纯文档不误触发")
    return 0


if __name__ == "__main__":
    sys.exit(main())
