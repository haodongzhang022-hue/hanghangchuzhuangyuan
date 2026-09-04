"""注册表与元数据测试"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from hanghang.engine import Registry, PrefixArchive


def test_registry_loads_units():
    reg = Registry()
    units = reg.all_units()
    assert len(units) >= 2, f"expected >= 2 units, got {len(units)}"
    uids = [u.unit_id for u in units]
    assert "dongjiagoushi" in uids


def test_registry_roles():
    reg = Registry()
    unit = reg.get_unit("dongjiagoushi")
    assert unit is not None
    role_names = [r.name for r in unit.roles]
    assert "architect" in role_names
    assert "developer" in role_names
    assert "product" in role_names
    assert "reviewer" in role_names


def test_prefix_archive():
    reg = Registry()
    prefixes = PrefixArchive()
    for unit in reg.all_units():
        prefixes.register_unit(unit)

    # 验证 dongjiagoushi 有前缀档案
    p = prefixes.get_unit_prefixes("dongjiagoushi")
    assert p is not None
    assert "[架构]" in p
    assert "[开发]" in p


if __name__ == "__main__":
    test_registry_loads_units()
    test_registry_roles()
    test_prefix_archive()
    print("✅ 注册表测试通过")
