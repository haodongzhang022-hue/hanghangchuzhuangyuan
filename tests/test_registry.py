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



def test_prefix_archive_atomic_save():
    """建议(原子写)：有漂移落盘走"同目录临时文件 + os.replace 原子替换"。

    1) 内容正确写入，可完整读回；
    2) 落盘后目录不残留 .prefix-archive-*.tmp 临时文件；
    3) 写失败(目标目录被置为只读等)时不残留临时文件且不影响已存在文件。
    """
    import glob
    import time as _time
    import tempfile as _tf
    from hanghang.engine.prefix import PrefixArchive

    reg = Registry()
    d = _tf.mkdtemp()
    archive_path = os.path.join(d, "prefix-archive.json")

    def leftover_tmp():
        return glob.glob(os.path.join(d, ".prefix-archive-*.tmp"))

    # 场景1：首次注册(有漂移)走原子落盘，内容完整 + 无临时残留
    pa = PrefixArchive(archive_file=archive_path)
    for unit in reg.all_units():
        pa.register_unit(unit)
    assert os.path.exists(archive_path)
    with open(archive_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert content.strip().endswith("}"), "应为完整合法 JSON 结尾"
    import json as _json
    _json.loads(content)  # 必须是合法 JSON，无半写截断
    assert not leftover_tmp(), "原子落盘后不应残留临时文件"

    # 场景2：产生真实漂移再落盘 → 仍原子替换、内容更新、无残留
    pa._archive["_drift_probe"] = {"industry": "probe", "role_prefixes": {}}
    _time.sleep(0.01)
    pa._save()  # 直接触发有漂移落盘
    with open(archive_path, "r", encoding="utf-8") as f:
        content2 = f.read()
    assert '"_drift_probe"' in content2, "漂移内容应已原子写入"
    _json.loads(content2)
    assert not leftover_tmp(), "漂移落盘后不应残留临时文件"

    # 场景3：目标目录不可写时失败 → 不残留临时文件、已有文件保持原状
    try:
        os.chmod(d, 0o555)  # 只读目录
    except OSError:
        pass
    before = open(archive_path, encoding="utf-8").read()
    try:
        pa._archive["_probe2"] = {"industry": "x"}
        pa._save()
        raised = False
    except OSError:
        raised = True
    finally:
        os.chmod(d, 0o755)
    # 只读目录下 mkstemp 必然抛 OSError（非 root）；root 下可能仍可写，故不强断言 raised
    if raised:
        assert not leftover_tmp(), "写失败不应残留临时文件"
        with open(archive_path, encoding="utf-8") as f:
            assert f.read() == before, "写失败不应污染既有档案"


if __name__ == "__main__":
    test_registry_loads_units()
    test_registry_roles()
    test_prefix_archive()
    test_prefix_archive_drift_aware_save()
    test_prefix_archive_atomic_save()
    print("✅ 注册表测试通过")
