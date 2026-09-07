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


def test_prefix_archive_drift_aware_save():
    """建议①：register_unit(persist=True) 采用"内容漂移才落盘"，幂等不触碰文件。

    1) 首次注册会写入档案文件；
    2) 用完全相同内容再次注册 → 文件内容与 mtime 均不变（无漂移不落盘）；
    """
    import tempfile
    import time as _time
    from hanghang.engine.prefix import PrefixArchive

    reg = Registry()
    archive_path = os.path.join(tempfile.mkdtemp(), "prefix-archive.json")

    # 场景1：首次注册落盘
    pa1 = PrefixArchive(archive_file=archive_path)
    for unit in reg.all_units():
        pa1.register_unit(unit)  # persist=True
    assert os.path.exists(archive_path), "首次注册应落盘"
    with open(archive_path, "r", encoding="utf-8") as f:
        first = f.read()
    assert '"dongjiagoushi"' in first
    first_mtime = os.path.getmtime(archive_path)

    # 场景2：无漂移再注册 → 不重写文件（内容、mtime 均不变）
    _time.sleep(0.01)  # 确保 mtime 可区分
    pa2 = PrefixArchive(archive_file=archive_path)
    for unit in reg.all_units():
        pa2.register_unit(unit)
    with open(archive_path, "r", encoding="utf-8") as f:
        second = f.read()
    assert second == first, "无漂移时内容不应变化"
    assert os.path.getmtime(archive_path) == first_mtime, "无漂移时不应重写文件"

    # 补充验证 archive 结构字段正确
    entry = pa2.get_archive()["dongjiagoushi"]
    assert entry["industry"]
    assert "[架构]" in [p["prefix"] for p in entry["role_prefixes"].values()]


if __name__ == "__main__":
    test_registry_loads_units()
    test_registry_roles()
    test_prefix_archive()
    test_prefix_archive_drift_aware_save()
    print("✅ 注册表测试通过")
