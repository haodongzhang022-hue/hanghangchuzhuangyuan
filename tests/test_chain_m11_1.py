"""M11.1 利益链条归一测试

要守住的事（就是这一层存在的理由）：
  1. 链上写行业类，不写具体公司 —— 写成公司形态必须被拦下
  2. 具体公司靠 index 现查 —— 类目到索引方案有映射，且索引不进画像库
  3. 叫法收敛 —— 同一类目几种叫法归一成一个，跨单元共享同一套口径
  4. 岗位引用 —— 跨单元岗位引用不用"行业 id"糊过去，要落到岗位 + unit
  5. 接进主链路 —— 岗位卡带归一后的链条，上下文注入用统一叫法
"""
from __future__ import annotations

import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../src"))

from hanghang.engine import Registry  # noqa: E402
from hanghang.rolecard import RoleCardStore  # noqa: E402
from hanghang.rolecard.chain import (  # noqa: E402
    CHAIN_FIELDS, IndustryClassIndex, unit_roles_from_registry,
)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(REPO, "src", "hanghang", "cli", "main.py")


def _store() -> RoleCardStore:
    return RoleCardStore(registry=Registry())


def _index(store: RoleCardStore) -> IndustryClassIndex:
    return store.classes


# ------------------------------------------------------- 1. 公司不落库
def test_company_name_rejected():
    """链上写成公司形态 → error（这就是"不要直接把公司存进来"的守门）。"""
    store = _store()
    idx = _index(store)
    for bad in ("某某钢材加工有限公司", "钢材加工厂", "某某集团"):
        assert idx.is_company_like(bad), f"{bad} 应识别为公司形态"
        issues = idx.validate("some-unit", "some_role", "upstream", [bad])
        assert any(i.level == "error" for i in issues), f"{bad} 未被拦下"
    # 行业类放行
    ok = idx.validate("some-unit", "some_role", "upstream", ["钢材加工"])
    assert not [i for i in ok if i.level == "error"]
    print("  ✅ test_company_name_rejected")


def test_real_profiles_have_no_company_names():
    """现有 50 个岗位画像里一个公司名都没有。"""
    store = _store()
    errors = [i for i in store.chain_issues() if i.level == "error"]
    assert not errors, "链条里仍有公司名/未登记类目:\n" + "\n".join(map(str, errors))
    print("  ✅ test_real_profiles_have_no_company_names")


# ------------------------------------------------------- 2. 类 → 索引
def test_class_resolves_to_index_not_records():
    """类目只带"检索方式"，不带任何公司名录。"""
    store = _store()
    idx = _index(store)
    entry = idx.resolve("钢材加工", "any-unit")
    assert entry.kind == "industry_class"
    assert entry.ref == "industry_class:钢材加工"
    assert isinstance(entry.index, dict) and entry.index.get("source")
    # 索引里只有查询方式，没有具体公司名
    blob = repr(entry.index)
    assert "有限" not in blob and "钢材加工厂" not in blob
    print("  ✅ test_class_resolves_to_index_not_records")


def test_class_usage_lists_roles():
    """类目能落到"被谁引用"的列表（这就是落的列表，不是落公司）。"""
    store = _store()
    usage = store.class_usage()
    assert "用户" in usage
    used_by = usage["用户"]["used_by"]
    assert len(used_by) > 1
    assert all({"unit", "role", "field"} <= set(u) for u in used_by)
    print("  ✅ test_class_usage_lists_roles")


# ------------------------------------------------------- 3. 叫法收敛
def test_alias_canonicalization():
    store = _store()
    idx = _index(store)
    assert idx.canonical("最终用户") == "用户"
    assert idx.canonical("用户（人）") == "用户"
    assert idx.canonical("业务执行方") == "业务方"
    assert idx.canonical("岗位产物口径不一致导致返工") == "跨岗口径不一致"
    # 归一后的说法一致，原文保留可追溯
    entry = idx.resolve("最终用户", "any-unit")
    assert entry.value == "用户" and entry.raw == "最终用户"
    print("  ✅ test_alias_canonicalization")


def test_unregistered_class_is_error():
    """没登记的类目 → error：防止同义词随便扩散。"""
    store = _store()
    idx = _index(store)
    issues = idx.validate("some-unit", "some_role", "upstream", ["某某不存在的行当"])
    assert any(i.level == "error" for i in issues)
    print("  ✅ test_unregistered_class_is_error")


# ------------------------------------------------------- 4. 岗位引用
def test_role_reference_keeps_unit():
    """引用别的单元的岗位：落到 role + unit，而不是写单元 id 糊过去。"""
    store = _store()
    idx = _index(store)
    same = idx.resolve("architect", "dongjiagoushi")
    assert same.kind == "role" and same.unit == "dongjiagoushi"
    cross = idx.resolve("teacher", "dongjiagoushi")
    assert cross.kind == "role" and cross.unit == "education-training"
    # 单元 id 也能解析（当行业类目），但要收敛成中文名
    unit = idx.resolve("design-visual", "marketing")
    assert unit.kind == "industry_class" and unit.value == "视觉设计"
    print("  ✅ test_role_reference_keeps_unit")


# ------------------------------------------------------- 5. 主链路
def test_card_exposes_normalized_chain():
    store = _store()
    card = store.get("dongjiagoushi", "developer")
    refs = card.chain_refs
    assert set(refs) == set(CHAIN_FIELDS)
    flat = [e for f in CHAIN_FIELDS for e in refs[f]]
    assert flat, "岗位卡没带归一后的链条"
    for e in flat:
        assert e["kind"] != "unregistered", f"未归一的引用: {e}"
        assert e["kind"] != "industry_class" or not any(
            m in e["raw"] for m in store.classes.company_markers)
    # 上下文注入用统一叫法
    block = card.to_context_block()
    assert "上游输入" in block
    print("  ✅ test_card_exposes_normalized_chain")


def test_cli_role_chain():
    for args, expect in [
        (["role", "chain", "developer", "--unit", "dongjiagoushi"], "利益链条"),
        (["role", "chain", "--check"], "链条校验"),
        (["role", "chain", "--class", "用户"], "被引用"),
        (["role", "chain", "--class", "钢材加工"], "索引"),
    ]:
        r = subprocess.run([sys.executable, CLI] + args, capture_output=True,
                           text=True, cwd=REPO)
        assert r.returncode == 0, f"{args} 退出码 {r.returncode}: {r.stderr[:300]}"
        assert expect in r.stdout, f"{args} 输出缺少 {expect}"
    print("  ✅ test_cli_role_chain")


def test_cli_chain_check_blocks_company():
    """校验命令在链上出现公司名时必须非 0 退出（CI 能拦住）。"""
    r = subprocess.run([sys.executable, CLI, "role", "chain", "--check"],
                       capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0
    assert "error 0" in r.stdout
    print("  ✅ test_cli_chain_check_blocks_company")


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
    print("✅ M11.1 利益链条归一测试全部通过" if not failed else f"❌ {failed} 个测试失败")
    raise SystemExit(1 if failed else 0)
