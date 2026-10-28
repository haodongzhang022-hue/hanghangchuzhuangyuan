"""职业分类大典参考表测试（M11 延伸）

核心断言：
1. 大典目录完整：8 大类 / 79 中类 / 449 小类 / 1636 细类，stats 自述不撒谎。
2. 编码可用：细类 code 唯一，能回溯到大类/中类/小类；L/S 标记与名称分离。
3. 映射不外键悬空：gb_code 必须真实存在，occur_id 必须真实存在于职业库。
4. **两个分母各管一件事**：映射率是"我们挂了多少"，大典覆盖度是
   "标准里还剩多少可选"。后者天然很小，不能被读成"还差 95% 没做完"。
5. 映射率有下限：不许为了"看起来齐整"批量删掉映射；也不许为了冲数字乱挂。
6. 参考表是旁证，不污染覆盖率：加了大典后 occupation_coverage 的分母不变。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from hanghang.engine.industry_db import IndustryDatabase
from hanghang.engine.occupation_catalog import CATALOG_FILE, MAP_FILE, OccupationCatalog


def _ids(db):
    return [o["id"] for o in db.occupations]


def test_catalog_scale_matches_stats():
    cat = OccupationCatalog()
    assert len(cat.occupations) == 1636
    assert len(cat.categories) == 8
    assert len(cat.middles) == 79
    assert len(cat.minors) == 449
    assert cat.stats["occupations"] == len(cat.occupations)
    assert cat.stats["categories"] == len(cat.categories)


def test_every_occupation_code_is_unique_and_parented():
    cat = OccupationCatalog()
    codes = [o["code"] for o in cat.occupations]
    assert len(codes) == len(set(codes)), "细类编码必须唯一"
    majors = {c["code"] for c in cat.categories}
    middles = {m["code"] for m in cat.middles}
    minors = {m["code"] for m in cat.minors}
    for o in cat.occupations:
        assert o["major"] in majors, o["code"]
        assert o["middle"] in middles, o["code"]
        assert o["minor"] in minors, o["code"]


def test_marks_split_from_name():
    """L/S 标记必须拆出来，不能留在名字里（否则按名匹配永远对不上）。"""
    cat = OccupationCatalog()
    for o in cat.occupations:
        assert not o["name"].endswith(("L", "S", "L/S")), o["name"]
        for m in o.get("marks") or []:
            assert m in ("L", "S"), f"{o['code']} 标记非法: {m}"
    assert len(cat.digital_occupations()) == 97
    assert len(cat.green_occupations()) == 133


def test_path_reads_like_a_sentence():
    cat = OccupationCatalog()
    path = cat.path_of("4-14-02-02")
    assert path == "社会生产服务和生活服务人员 / 健康、体育和休闲服务人员 / 健康咨询服务人员"


def test_mapping_has_no_dangling_foreign_keys():
    db = IndustryDatabase()
    problems = db.catalog.validate(_ids(db))
    assert problems == [], problems


def test_validate_reports_unknown_gb_code():
    """悬空 code 必须报出来——静默返回空串会让映射看起来"生效了"。"""
    db = IndustryDatabase()
    cat = db.catalog
    cat.maps = list(cat.maps) + [
        {"occur_id": "developer", "gb_code": "9-99-99-99", "confidence": "exact"}]
    cat._reindex()
    problems = cat.validate(_ids(db))
    assert any("不在大典目录中" in p for p in problems), problems
    assert any("occur_id 重复" in p for p in problems), problems


def test_validate_reports_stale_occur_id():
    """职业改名/删除后映射会悬空，这种静默失效比没有映射更坏。"""
    db = IndustryDatabase()
    cat = db.catalog
    cat.maps = list(cat.maps) + [
        {"occur_id": "ghost-occupation", "gb_code": "2-02-10-03",
         "confidence": "near"}]
    cat._reindex()
    problems = cat.validate(_ids(db))
    assert any("ghost-occupation" in p for p in problems), problems


def test_map_rate_floor():
    """映射率下限：映射是人工核对的资产，不能被随手删光。

    47.6% 是当前实际水平；留 40% 余量，让正常增补不被卡住，
    同时挡住"大典文件丢了映射全空还自称通过"。
    """
    db = IndustryDatabase()
    cov = db.catalog.coverage(_ids(db))
    assert cov["mapped_occupations"] >= 60
    assert cov["map_rate"] >= 0.40, cov["map_rate"]


def test_mapped_codes_are_real_and_unique_per_occupation():
    """一个职业只挂一个 code；反过来同一 code 可被多个职业复用（翻译三兄弟）。"""
    db = IndustryDatabase()
    cat = db.catalog
    seen = {}
    for o in db.occupations:
        gb = cat.gb_code_of(o["id"])
        if not gb:
            continue
        assert gb not in seen or seen[gb] != o["id"]
        seen[gb] = o["id"]
        assert cat.entry(gb) is not None, f"{o['id']} 的 {gb} 不在目录里"
    assert sum(1 for m in cat.maps) == len({m["occur_id"] for m in cat.maps})


def test_catalog_coverage_is_not_confused_with_map_rate():
    """两个分母别混读：大典覆盖度 4% 是正常的，映射率 47% 才是进度指标。"""
    db = IndustryDatabase()
    cov = db.catalog.coverage(_ids(db))
    assert cov["total_catalog_occupations"] == 1636
    # 覆盖的 code 数 == 映射里出现的不同 code 数（按 code 去重，不按职业数）
    distinct = {m["gb_code"] for m in db.catalog.maps}
    assert cov["catalog_codes_covered"] == len(distinct)
    assert cov["catalog_codes_covered"] < cov["total_catalog_occupations"]


def test_catalog_does_not_inflate_coverage_denominator():
    """参考表只是旁证：职业覆盖率分母仍是 baseline_occupation，没被 1636 稀释。"""
    db = IndustryDatabase()
    s = db.compute()
    assert s["baseline_occupations"] == 139
    assert s["total_occupations"] == 147
    assert s["occupation_coverage"] == 1.0
    assert s["catalog"]["available"] is True
    assert s["catalog"]["mapped_occupations"] == 70


def test_search_and_entry_roundtrip():
    cat = OccupationCatalog()
    hits = cat.search("健康管理师")
    assert len(hits) == 1
    e = cat.entry(hits[0]["code"])
    assert e["name"] == "健康管理师"
    assert cat.search("不可能存在的职业名XYZ") == []


def test_unmapped_gaps_excludes_linked_codes():
    db = IndustryDatabase()
    ids = _ids(db)
    gaps = db.catalog.unmapped_gaps(ids, limit=0)
    linked = {db.catalog.gb_code_of(i) for i in ids} - {""}
    gap_codes = {g["code"] for g in gaps}
    assert not (gap_codes & linked)
    assert len(gaps) == 1636 - len(linked)
    # 大类筛选生效
    major2 = db.catalog.unmapped_gaps(ids, major="2", limit=0)
    assert all(g["major"] == "2" for g in major2)


def test_missing_catalog_degrades_but_validate_complains(tmp_path):
    """参考表缺失时主库仍可用，但 check 必须报出来，不能静默当健康。"""
    db = IndustryDatabase()
    db.catalog = None
    problems = db.validate()
    assert any("职业大典参考表未加载" in p for p in problems), problems
    # 主库自身的统计不受影响
    s = db.compute()
    assert s["catalog"]["available"] is False
    assert s["occupation_coverage"] == 1.0


def test_reference_files_exist():
    cat = OccupationCatalog()
    assert os.path.exists(cat.catalog_path), cat.catalog_path
    assert os.path.exists(cat.map_path), cat.map_path
    assert os.path.basename(cat.catalog_path) == CATALOG_FILE
    assert os.path.basename(cat.map_path) == MAP_FILE


def test_export_carries_gb_columns(tmp_path):
    import json
    import sqlite3
    from hanghang.cli.industry_commands import cmd_industry_export

    class Args:
        out = str(tmp_path / "out")
        format = "all"
        data_dir = ""

    cmd_industry_export(Args)
    data = json.load(open(os.path.join(Args.out, "industry-db.json"), encoding="utf-8"))
    mapped = [o for o in data["occupations"] if o.get("gb_code")]
    assert len(mapped) == 70
    assert mapped[0]["gb_name"] and mapped[0]["gb_path"]
    conn = sqlite3.connect(os.path.join(Args.out, "industry.sqlite"))
    assert conn.execute("select count(*) from gb_catalog").fetchone()[0] == 1636
    row = conn.execute(
        "select gb_code, gb_name from occupation where id='health-consultant'").fetchone()
    assert row == ("4-14-02-02", "健康管理师")
    conn.close()


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            if fn.__code__.co_argcount:
                import tempfile
                with tempfile.TemporaryDirectory() as d:
                    from pathlib import Path
                    fn(Path(d))
            else:
                fn()
            print(f"  ✅ {name}")
    print("\n✅ test_occupation_catalog.py 全部通过")
