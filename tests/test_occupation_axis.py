"""原子岗位 + 软归属（模糊分类）测试

用户拍板的模型：
  岗位原子化，每个岗位一个唯一编号；分类/聚类是**筛选器**，不是户籍。
  一个岗位被多个视角同时看见是常态，权重不必相加为 100，
  分区改名/拆分/合并都不该动到岗位记录本身。

这组断言守的就是这几条，防止下一次改动又把"硬归属"悄悄装回来：
1. 职业表里不得出现归属字段（unit_id / unit_role）——一有就退回单值归属。
2. 唯一编号必须唯一、格式正确、与登记序号一致，且能被编号反查。
3. 同一职业可同时被多个视角引用，权重各自独立（不要求相加为 1）。
4. 同一 (职业,分区,轴) 不得重复；权重必须落在 (0,1]；边不得指向不存在分区。
5. 分类是筛选器：不同条件筛出不同结果，没有"正确归属"这回事。
6. 改聚类不影响岗位：删边/改权重/重命名分区后，职业记录一条不少。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from hanghang.engine import occupation_axis as oa
from hanghang.engine.industry_db import IndustryDatabase


def _db():
    return IndustryDatabase()


# --------------------------------------------------------------- 原子化
def test_occupation_has_no_ownership_field():
    """原子岗位：职业记录里不得有"我属于谁"的字段"""
    db = _db()
    for o in db.occupations:
        assert "unit_id" not in o, f"{o['id']} 残留单值归属字段 unit_id"
        assert "unit_role" not in o, f"{o['id']} 残留单值岗位名字段 unit_role"


def test_every_occupation_has_unique_code():
    """唯一岗位编号：格式 OCC-######，唯一，且与登记序号一致"""
    db = _db()
    codes = [o.get("code") for o in db.occupations]
    assert all(c and oa.parse_code(c) is not None for c in codes), codes[:5]
    assert len(codes) == len(set(codes)), "编号必须唯一"
    for i, o in enumerate(db.occupations, 1):
        assert oa.parse_code(o["code"]) == i, f"{o['id']} 编号与序号不一致"


def test_code_lookup_works():
    """按编号能直接查到岗位：跨表对齐靠它，不靠名字"""
    db = _db()
    first = db.occupations[0]
    hit = db.axis_view._occ_by_code.get(first["code"])
    assert hit is not None and hit["id"] == first["id"]


def test_occupation_ids_do_not_depend_on_partition_name():
    """分区改名/别名变更不影响职业：改的是看法，不是人"""
    db = _db()
    before = [(o["id"], o.get("code")) for o in db.occupations]
    p = db.partition("dongjiagoushi")
    p["name"] = "软件与信息服务（改名验证）"
    p["aliases"] = (p.get("aliases") or []) + ["新叫法"]
    after = [(o["id"], o.get("code")) for o in db.occupations]
    assert before == after
    assert db.validate() == []


# --------------------------------------------------------------- 软归属
def test_one_occupation_seen_by_many_views():
    """同一职业被多个视角同时引用：这是模型的核心，不是数据脏"""
    db = _db()
    views = {m["partition"] for m in db.views_of_occupation("data-analyst")}
    assert len(views) >= 3, views
    s = db.compute()
    assert s["multi_view_occupations"] >= 1


def test_weights_need_not_sum_to_one():
    """权重是"这份看法有多重"，不是概率分布，不要求和为 1"""
    db = _db()
    weights = [db.axis_view._weight(m) for m in
               db.views_of_occupation("data-analyst")]
    assert len(weights) >= 2
    assert all(0 < w <= 1 for w in weights)
    # 故意让某个职业在同一根轴上的总权重明显不等于 1，验证不会被判错
    db.axis_view.refresh(
        [{"occupation": "data-analyst", "partition": "e-commerce",
          "axis": "occupation", "weight": 0.6},
         {"occupation": "data-analyst", "partition": "marketing",
          "axis": "occupation", "weight": 0.5}])
    db._memberships_raw = [dict(m) for m in db.axis_view.memberships]
    db._reindex()
    problems = db.validate()
    assert not any("weight" in p or "重复归属" in p for p in problems), problems


def test_primary_view_is_filtered_by_weight():
    """筛选器用法：只看主要归属（权重 >= 0.5）"""
    db = _db()
    primary = {m["partition"] for m in db.axis_view.primary_of("data-analyst")}
    assert "data-analytics" in primary
    assert "finance-accounting" not in primary


def test_filter_is_a_sieve_not_a_verdict():
    """同一职业在不同条件下出现在不同结果里，没有"唯一正确归属"这回事"""
    db = _db()
    by_ecom = {o["id"] for o in db.axis_view.filter(partition="e-commerce")}
    by_fin = {o["id"] for o in db.axis_view.filter(partition="finance-accounting")}
    assert "data-analyst" in by_ecom
    assert "data-analyst" in by_fin
    ai_in_ecom = {o["id"] for o in db.axis_view.filter(
        partition="e-commerce", provider="ai")}
    assert ai_in_ecom <= by_ecom


def test_partition_removal_keeps_occupations():
    """删掉一个视角：职业一条不少，只是不再被这个角度看得到"""
    db = _db()
    total_before = len(db.occupations)
    seen_before = {o["id"] for o in db.members_of("data-analytics")}
    db.axis_view.refresh([m for m in db.axis_view.memberships
                          if m["partition"] != "data-analytics"])
    db._memberships_raw = [dict(m) for m in db.axis_view.memberships]
    db._reindex()
    assert len(db.occupations) == total_before
    assert db.members_of("data-analytics") == []
    for occ_id in seen_before:
        assert db.occupation(occ_id) is not None, "岗位不该跟着视角一起消失"


def test_free_occupations_are_not_gaps():
    """没有任何视角引用的职业照样在册：原子岗位不靠归属活着"""
    db = _db()
    free = db.axis_view.free_occupations()
    codes = {o["code"] for o in db.occupations}
    for o in free:
        assert o["code"] in codes
    assert len(free) + len(db.axis_view._by_occ) >= len(db.occupations) - len(free)


# --------------------------------------------------------------- 校验
def test_duplicate_edge_is_reported():
    """同一 (职业,分区,轴) 两条边 = 同一件事说了两遍，必须报"""
    db = _db()
    edge = dict(db.axis_view.memberships[0])
    db.axis_view.refresh(list(db.axis_view.memberships) + [edge])
    db._memberships_raw = [dict(m) for m in db.axis_view.memberships]
    db._reindex()
    problems = db.validate()
    assert any("重复归属" in p for p in problems), problems


def test_out_of_range_weight_is_reported():
    """权重越界（<=0 或 >1）必须报：写 0 只会制造噪音"""
    for bad in (0, 0.0, -0.3, 1.5):
        db = _db()
        edges = [dict(m) for m in db.axis_view.memberships]
        edges[0]["weight"] = bad
        db.axis_view.refresh(edges)
        db._memberships_raw = [dict(m) for m in db.axis_view.memberships]
        db._reindex()
        problems = db.validate()
        assert any("weight" in p for p in problems), (bad, problems)


def test_edge_to_unknown_partition_is_reported():
    """边指向不存在的分区 = 悬空，必须报（不然这个视角静默什么都查不到）"""
    db = _db()
    edges = [dict(m) for m in db.axis_view.memberships]
    edges.append({"occupation": db.occupations[0]["id"],
                  "partition": "ghost-view", "axis": "occupation", "weight": 0.5})
    db.axis_view.refresh(edges)
    db._memberships_raw = [dict(m) for m in db.axis_view.memberships]
    db._reindex()
    problems = db.validate()
    assert any("ghost-view" in p for p in problems), problems


def test_unknown_axis_on_edge_is_reported():
    """边写在未知轴上 = 任何视角都查不到，必须报"""
    db = _db()
    edges = [dict(m) for m in db.axis_view.memberships]
    edges[0]["axis"] = "galaxy"
    db.axis_view.refresh(edges)
    db._memberships_raw = [dict(m) for m in db.axis_view.memberships]
    db._reindex()
    problems = db.validate()
    assert any("galaxy" in p for p in problems), problems


def test_missing_code_is_reported():
    """缺少唯一编号必须报：没有身份证就无法跨表对齐"""
    db = _db()
    db.occupations[3].pop("code", None)
    problems = db.validate()
    assert any("唯一编号" in p for p in problems), problems


def test_duplicate_code_is_reported():
    db = _db()
    db.occupations[4]["code"] = db.occupations[3].get("code")
    problems = db.validate()
    assert any("职业编号重复" in p for p in problems), problems


def test_legacy_unit_id_still_recognized():
    """老数据兼容：只剩单值 unit_id 时仍能推出等价的一条边（weight=1）"""
    db = _db()
    db.occupations.append({"id": "legacy-occ", "code": "OCC-999999",
                           "name": "老格式职业", "unit_id": "translation",
                           "deliverable": "文本", "provider": "ai",
                           "billing": "usage", "baseline_occupation": False})
    # 只给职业、不给边：视图应当从单值字段推出一条等价边
    db.axis_view = oa.OccupationAxis(db.occupations, db.partitions, None)
    edges = db.views_of_occupation("legacy-occ")
    assert len(edges) == 1 and edges[0]["partition"] == "translation"
    assert edges[0]["legacy"] is True




# --------------------------------------------- 校验条数：一个数，一个来源
def test_validate_check_count_is_single_source():
    """校验条数只许有一个来源：代码常量。

    README 说 15、文档标题说 17、代码实际 18 —— 这个数被手抄三份就会这样。
    这里把"三个数必须相等"钉死：文档表格行数、文档标题、README 说法都读常量。
    """
    db = _db()
    n = db.VALIDATE_CHECK_COUNT
    root = os.path.join(os.path.dirname(__file__), "..")
    doc = open(os.path.join(root, "docs/industry/industry-partition-db.md"),
               encoding="utf-8").read()
    readme = open(os.path.join(root, "README.md"), encoding="utf-8").read()
    assert f"的 {n} 条校验" in doc, f"文档标题的条数不是 {n}"
    assert f"跑 {n} 条校验" in readme, f"README 的条数不是 {n}"

    import re
    rows = [ln for ln in doc.splitlines() if re.match(r"^\| \d+ \|", ln)]
    assert len(rows) == n, f"文档表格有 {len(rows)} 行，常量说 {n}"


def test_docstring_check_points_are_contiguous():
    """validate() docstring 里的校验点编号必须 1..N 连续，且与常量一致"""
    import inspect
    import re
    src = inspect.getsource(IndustryDatabase.validate)
    nums = [int(x) for x in re.findall(r"^        (\d+)\. ", src, re.M)]
    assert nums == list(range(1, IndustryDatabase.VALIDATE_CHECK_COUNT + 1)), nums


def test_cli_check_receipt_reads_constant():
    """CLI 回执不许写死条数：改了常量，回执跟着变"""
    import subprocess
    root = os.path.join(os.path.dirname(__file__), "..")
    out = subprocess.run(
        [sys.executable, os.path.join(root, "src/hanghang/cli/main.py"),
         "industry", "check"],
        capture_output=True, text=True, cwd=root)
    assert out.returncode == 0, out.stderr
    assert f"{IndustryDatabase.VALIDATE_CHECK_COUNT} 条校验" in out.stdout, out.stdout


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ✅ {name}")
    print("✅ 原子岗位 + 软归属测试通过")
