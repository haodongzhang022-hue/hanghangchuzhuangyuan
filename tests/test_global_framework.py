"""全球分类框架测试：ISCO-08 参考表 + 四根轴索引（M11 延伸）

核心断言：
1. ISCO-08 完整：10/43/130/436，stats 自述与实际条数一致，编码位数即层级。
2. 归属链路不断：任何 4 位细类的上级三级都能查到（按码查归属不许断在半路）。
3. 官方示例职位名是这套表最值钱的东西：1931 条，能当英文工种名的入口。
4. **ISCO 不参与 coverage 分母**：加了 436 个细类，职业基线不被稀释（<200，具体数随补全增长）。
5. 四根轴齐全：职业/行业/税收/产出，税收必须单独成轴（不许当行业码用）。
6. 索引自检有效：axis 写错、status 写错、integrated 没落地路径，都必须报出来。
7. 参考表缺失不能被当成"没有映射所以没问题"——必须报 problems。
"""
import os
import shutil
import sys
import tempfile

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from hanghang.engine.global_framework import (
    AXES, IscoCatalog, ClassificationSources, ISCO_FILE, SOURCES_FILE,
)
from hanghang.engine.industry_db import IndustryDatabase

REF_DIR = os.path.join(os.path.dirname(__file__), "../data/reference")


# ---------------------------------------------------------------- ISCO 表
def test_isco_scale_matches_stats():
    cat = IscoCatalog(REF_DIR)
    for lvl, key in ((1, "major_groups"), (2, "sub_major_groups"),
                     (3, "minor_groups"), (4, "unit_groups")):
        assert len(cat.by_level[lvl]) == cat.stats[key], f"{key} 与 stats 不符"
    assert cat.stats == {"major_groups": 10, "sub_major_groups": 43,
                         "minor_groups": 130, "unit_groups": 436}


def test_code_length_is_level_and_parent_exists():
    cat = IscoCatalog(REF_DIR)
    for lvl in (1, 2, 3, 4):
        for r in cat.by_level[lvl]:
            code = r["code"]
            assert len(code) == lvl, f"{code} 位数与层级不符"
            assert cat.level_of(code) == lvl
            if lvl > 1:
                assert cat.entry(code[:-1]), f"{code} 的上级 {code[:-1]} 缺失"
    assert cat.validate() == []


def test_path_reaches_from_major_to_unit():
    cat = IscoCatalog(REF_DIR)
    path = cat.path_of("2512")
    names = path.split(" / ")
    assert len(names) == 4, path
    assert names[0] == "Professionals"
    assert names[-1] == "Software developers"


def test_official_examples_are_searchable():
    """示例职位名是"这工种在英文里到底叫什么"的入口，缺了这套表就只剩 436 个抽象名。"""
    cat = IscoCatalog(REF_DIR)
    assert cat.example_count() >= 1500, cat.example_count()
    hits = cat.search("software engineer")
    assert any(h["code"] == "2512" for h in hits), "示例名搜不到细类"
    assert "Software engineer" in cat.entry("2512")["examples"]


def test_children_and_search_limits():
    cat = IscoCatalog(REF_DIR)
    kids = cat.children_of("25")
    assert kids and all(k["code"].startswith("25") and len(k["code"]) == 3 for k in kids)
    assert cat.children_of("2512") == []
    assert len(cat.search("nurse", limit=2)) == 2


def test_missing_isco_table_is_reported_not_silent():
    tmp = tempfile.mkdtemp()
    problems = IscoCatalog(tmp).validate()
    assert problems and "未加载或为空" in problems[0]


def test_isco_does_not_dilute_denominator():
    """参考表是旁证：436 个细类进来后，职业基线分母不许变。"""
    db = IndustryDatabase()
    before = db.compute()["occupation_coverage"]
    db2 = IndustryDatabase()
    db2.isco = None
    after = db2.compute()["occupation_coverage"]
    assert before == after
    # 分母不被外部全集稀释：基线职业数远小于大典 1636（具体数字随补全增长）
    assert db.compute()["baseline_occupations"] < 200


# ------------------------------------------------------------ 四根轴索引
def test_axes_cover_occupation_industry_tax_output():
    src = ClassificationSources(REF_DIR)
    assert set(src.axes) == set(AXES)
    assert src.validate() == []
    for axis in AXES:
        assert src.by_axis(axis), f"{axis} 轴没有登记任何标准"


def test_tax_is_its_own_axis_not_industry():
    """税目不是行业码：税率跟"卖的是什么"走。混轴会让一次税率调整污染聚类表。"""
    src = ClassificationSources(REF_DIR)
    tax = src.by_axis("tax")
    assert tax, "税收轴必须单独存在"
    industry_ids = {s["id"] for s in src.by_axis("industry")}
    assert not ({t["id"] for t in tax} & industry_ids)


def test_integrated_sources_declare_landing_path():
    src = ClassificationSources(REF_DIR)
    done = src.by_status("integrated")
    assert {s["id"] for s in done} >= {"CN-OCC-2022", "ISCO-08"}
    for s in done:
        assert s.get("we_have"), f"{s['id']} 标记已接入但没写落地路径"
        assert os.path.exists(os.path.join(os.path.dirname(__file__), "..",
                                          s["we_have"])), s["we_have"]


def test_index_validation_catches_axis_and_status_typos():
    tmp = tempfile.mkdtemp()
    data = yaml.safe_load(open(os.path.join(REF_DIR, SOURCES_FILE), encoding="utf-8"))
    data["sources"][0]["axis"] = "industries"       # 拼错
    data["sources"][1]["status"] = "done"           # 拼错
    data["sources"][2]["we_have"] = ""              # integrated 没落地
    yaml.safe_dump(data, open(os.path.join(tmp, SOURCES_FILE), "w", encoding="utf-8"),
                   allow_unicode=True)
    problems = ClassificationSources(tmp).validate()
    assert any("axis=" in p for p in problems)
    assert any("status=" in p for p in problems)
    assert any("integrated" in p for p in problems)


# --------------------------------------------------------- 与自检的接线
def _db_with_reference(mutate=None):
    """复制真实数据到临时目录，按需破坏 reference 目录。"""
    tmp = tempfile.mkdtemp()
    for name in ("industry-occupations.yaml", "industry-partitions.yaml",
                 "industry-register.yaml", "unit-index.yaml",
                 "coverage-target.yaml", "context-rules.yaml"):
        src = os.path.join(os.path.dirname(__file__), "../data", name)
        if os.path.exists(src):
            shutil.copy(src, os.path.join(tmp, name))
    ref = os.path.join(tmp, "reference")
    os.makedirs(ref)
    for name in os.listdir(REF_DIR):
        shutil.copy(os.path.join(REF_DIR, name), os.path.join(ref, name))
    if mutate:
        mutate(ref)
    return IndustryDatabase(data_dir=tmp)


def test_real_data_has_no_problems():
    """现实数据只剩"待建分区骨架没人认领"这一类已知缺口（见 test_industry_completion）"""
    db = IndustryDatabase()
    others = [p for p in db.validate() if "骨架悬空" not in p]
    assert others == [], others


def test_missing_global_reference_is_a_problem():
    db = _db_with_reference(lambda ref: os.remove(os.path.join(ref, ISCO_FILE)))
    problems = db.validate()
    assert any("ISCO" in p for p in problems), problems
    # 主库本身不能因为旁证缺失就变成不可用
    assert db.compute()["baseline_occupations"] < 200


def test_broken_isco_parent_is_a_problem():
    def mutate(ref):
        path = os.path.join(ref, ISCO_FILE)
        data = yaml.safe_load(open(path, encoding="utf-8"))
        data["unit_groups"][0]["code"] = "99999"
        yaml.safe_dump(data, open(path, "w", encoding="utf-8"), allow_unicode=True)

    problems = _db_with_reference(mutate).validate()
    assert any("99999" in p for p in problems), problems


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ✅ {name}")
    print("\n✅ test_global_framework.py 全部通过")
