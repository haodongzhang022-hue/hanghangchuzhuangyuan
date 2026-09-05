#!/usr/bin/env python3
"""全量测试运行器：运行 tests/ 下所有测试文件"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_DIR = os.path.join(ROOT, "tests")
SRC_DIR = os.path.join(ROOT, "src")

sys.path.insert(0, SRC_DIR)


def run_tests():
    """运行 tests/ 目录下所有 test_*.py"""
    failed = []
    passed = 0

    for f in sorted(os.listdir(TESTS_DIR)):
        if not f.startswith("test_") or not f.endswith(".py"):
            continue
        path = os.path.join(TESTS_DIR, f)
        print(f"\n==== 运行: {f} ====")
        rc = subprocess.call([sys.executable, path], cwd=ROOT)
        if rc != 0:
            failed.append(f)
            print(f"  ❌ {f} 失败")
        else:
            passed += 1
            print(f"  ✅ {f} 通过")

    print(f"\n通过: {passed} 个测试文件, 失败: {len(failed)}")
    if failed:
        print(f"失败文件: {failed}")
        return 1
    print("\n✅ 全部测试通过")
    return 0


def smoke_test():
    """CLI 冒烟测试"""
    from hanghang.engine import Registry, IntentRouter, CompositePlanner

    reg = Registry()
    router = IntentRouter(reg)

    # 测试路由
    cases = [
        ("架构设计方案", "dongjiagoushi", ["architect"], False),
        ("帮我点个外卖", "", [], True),  # 回落人工
    ]

    for text, expect_unit, expect_roles, expect_manual in cases:
        r = router.route(text)
        ok = True
        if expect_unit:
            ok = ok and r.unit_id == expect_unit
        if expect_roles:
            ok = ok and all(role in r.roles for role in expect_roles)
        ok = ok and r.needs_manual == expect_manual
        if not ok:
            print(f"  ❌ 冒烟失败: {text} → unit={r.unit_id}, roles={r.roles}, manual={r.needs_manual}")
            return False
        print(f"  ✅ 冒烟通过: {text}")

    return True


if __name__ == "__main__":
    rc1 = run_tests()
    print("\n==== CLI 冒烟测试 ====")
    rc2 = 0 if smoke_test() else 1
    sys.exit(rc1 or rc2)
