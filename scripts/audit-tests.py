#!/usr/bin/env python3
"""测试冗余与覆盖审计工具（Test Coverage / Redundancy Audit）v1

用途（对齐 Issue #8「改良加载机制」下的测试瘦身诉求）：
  1) 覆盖矩阵：每个 hanghang 源码模块 -> 被哪些测试文件覆盖；找出"未被任何测试直接鉴定"的模块；
  2) 冗余识别：同一源码被过多测试文件覆盖（同质重复）；同一测试文件内高度同构的用例；
  3) 输出校准清单：哪些测试可精简、哪些源码模块缺鉴定。

用法：
  python3 scripts/audit-tests.py            # 全仓审计
  python3 scripts/audit-tests.py --by-file  # 附带逐测试文件的覆盖明细
退出码：恒为 0（报告性质，不阻断流水线）。
"""
import os, re, sys, glob
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

def walk_py(pkg_dir):
    out = []
    for dp, _, fs in os.walk(pkg_dir):
        for fn in fs:
            if fn.endswith(".py"):
                out.append(os.path.join(dp, fn))
    return out

def src_abs(p):
    return os.path.normpath(os.path.join("src", p))

def covered_src(test_file):
    """test_file import 到的 hanghang 源码文件集合。"""
    src = open(test_file).read()
    mods = set(m.group(1) for m in re.finditer(r'^(?:from|import)\s+([\w.]+)', src, re.M)
               if m.group(1).startswith("hanghang"))
    files = set()
    for mod in mods:
        p = mod.replace(".", "/")
        for cand in (os.path.join("src", p) + ".py", os.path.join("src", p)):
            if os.path.isfile(cand):
                files.add(cand)
            elif os.path.isdir(cand):
                files.update(walk_py(cand))
    if not files:  # 解析不到源码（如 e2e 靠子进程/import 不显式）-> 整仓源码兜底
        files.update(walk_py("src"))
    return files

def test_methods(test_file):
    src = open(test_file).read()
    return re.findall(r'^\s*def (test_\w+)', src, re.M)

def main():
    only_by_file = "--by-file" in sys.argv
    test_files = sorted(glob.glob("tests/test_*.py"))
    src_files = sorted(walk_py("src"))

    # 源码模块 -> 覆盖它的测试文件
    src2tests = defaultdict(set)
    for tf in test_files:
        for sf in covered_src(tf):
            src2tests[sf].add(tf)

    # 每个测试文件的方法数
    tf_methods = {tf: test_methods(tf) for tf in test_files}

    print("=" * 70)
    print("测试覆盖与冗余审计  Test Coverage / Redundancy Audit")
    print("=" * 70)
    print(f"源码模块: {len(src_files)}   测试文件: {len(test_files)}")

    # ---- 1. 未被任何测试直接鉴定的源码模块（"还没有鉴定"） ----
    print("\n## 1. 未被任何测试直接鉴定的源码模块（可能缺鉴定）")
    missing = [s for s in src_files if s not in src2tests]
    if missing:
        for s in sorted(missing):
            print(f"   · {s}")
    else:
        print("   · （无：所有 hanghang 源码模块均被至少一个测试文件覆盖）")

    # ---- 2. 覆盖密度过高 → 冗余风险 ----
    print("\n## 2. 覆盖重复度较高的源码模块（被过多测试文件同时覆盖 → 冗余/重复测试风险）")
    dense = [(s, sorted(ts)) for s, ts in src2tests.items() if len(ts) >= 4]
    for s, ts in sorted(dense, key=lambda x: -len(x[1])):
        total = sum(len(tf_methods[t]) for t in ts)
        print(f"   · {s}  <- 被 {len(ts)} 个测试文件覆盖，累计 {total} 个用例")
        if only_by_file:
            for t in ts:
                print(f"        {t} ({len(tf_methods[t])} 用例)")

    # ---- 3. 高密度跨文件重复簇 ----
    print("\n## 3. 高度同源重复簇（同源码、多数用例，适合合并/精简到单域）")
    # 用“engine 路由/注册表”视为同一聚合域，找出覆盖它的文件组
    engine_files = [s for s in src_files if "/engine/" in s]
    routing_tests = set()
    for s in engine_files:
        routing_tests.update(src2tests.get(s, []))
    routing_tests = [t for t in routing_tests if "state" not in t and "web" not in t]
    if routing_tests:
        total = sum(len(tf_methods[t]) for t in routing_tests)
        print(f"   · engine 核心域由 {len(routing_tests)} 个文件、共 {total} 个用例覆盖：")
        for t in sorted(routing_tests):
            print(f"        {t} ({len(tf_methods[t])} 用例)")

    # ---- 4. 汇总建议 ----
    print("\n## 4. 瘦身建议（change-aware v3 已自动避免的，手动清理可选）")
    print("   - 重复的用例级覆盖已被 change-aware 的『结果缓存』自动跳过，不再每次全跑；")
    print("   - 建议聚焦【第1节 缺鉴定模块】补齐测试；对【第2/3节 高覆盖簇】按模块拆分精简。")
    print("\n（审计结束；报告仅供校准，不阻断流水线）")

if __name__ == "__main__":
    main()
