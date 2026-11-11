"""职业分类大典参考表 · occupation-catalog

设计立场：**大典是权威分类口径，我们是执行单元口径，两者不混为一谈。**

- data/reference/occupation-catalog-2022.yaml 原样收下《职业分类大典（2022年版）》
  的 1636 个细类职业（8 大类 / 79 中类 / 449 小类），只读、不改、不裁剪。
- data/reference/occupation-gb-map.yaml 存"我们自己的职业" ↔ 大典细类 code 的
  人工映射。宁缺勿错：口径对不上的就留空，不用模糊匹配硬凑。

为什么不全量倒进 industry-occupations.yaml：
    大典 1636 条里绝大多数（军队人员、矿业工种、不便分类）既没有付费方也没有
    可交付物，塞进职业库只会把覆盖率稀释成没意义的数字。它们在**补全缺口时**
    才是财富 —— 所以单独放参考表，按需查表挑，而不是伪装成"已登记职业"。

覆盖口径（两个分母各管一件事，别混着读）：
    * 大典映射率 = 已挂 gb_code 的职业数 / 职业库总数
    * 大典覆盖度 = 已挂 gb_code 的大典 code 数 / 大典 1636 个细类
      第二个数字天然很小，因为绝大多数大典细类（军队、采矿工种…）不会单独建
      数字员工单元。**注意：不建单元 ≠ 不登记** —— 军队/采矿这些职业照样在
      industry-occupations.yaml 里，用 access 标出承接通道（财政供养/现场作业），
      画像、付费方、就业口径一个都不少。这个数字的用处是"标准里还剩多少可选"，
      不是"还差多少要补"。
"""
from __future__ import annotations

import logging
import os
import re
from typing import Dict, List, Optional

import yaml

CATALOG_FILE = "occupation-catalog-2022.yaml"
MAP_FILE = "occupation-gb-map.yaml"

_MARK_RE = re.compile(r"(L/S|L|S)$")


def _split_marks(name: str):
    """职业名尾部的 L(绿色职业)/S(数字职业)/L/S 拆成 marks，做筛选时用。"""
    m = _MARK_RE.search(name or "")
    if not m:
        return name or "", []
    return name[: -len(m.group(1))].strip(), [t for t in m.group(1).split("/") if t]


class OccupationCatalog:
    """大典参考表 + 映射表。只读，不做落盘。"""

    def __init__(self, data_dir: Optional[str] = None):
        self.data_dir = data_dir or self._find_data_dir()
        self.ref_dir = os.path.join(self.data_dir, "reference")
        self.catalog_path = os.path.join(self.ref_dir, CATALOG_FILE)
        self.map_path = os.path.join(self.ref_dir, MAP_FILE)
        self.version = ""
        self.updated_at = ""
        self.stats: Dict[str, int] = {}
        self.categories: List[dict] = []
        self.middles: List[dict] = []
        self.minors: List[dict] = []
        self.occupations: List[dict] = []
        self.maps: List[dict] = []
        self._load()

    @staticmethod
    def _find_data_dir() -> str:
        cands = [os.path.join(os.getcwd(), "data"),
                 os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "../../data")]
        for c in cands:
            if os.path.isdir(c):
                return os.path.abspath(c)
        return os.path.abspath(cands[0])

    def _load(self) -> None:
        if os.path.exists(self.catalog_path):
            with open(self.catalog_path, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
            self.version = data.get("version", "")
            self.stats = data.get("stats", {}) or {}
            self.categories = data.get("categories", []) or []
            self.middles = data.get("middles", []) or []
            self.minors = data.get("minors", []) or []
            self.occupations = data.get("occupations", []) or []
        else:
            logging.warning(f"缺少职业大典目录: {self.catalog_path}")

        if os.path.exists(self.map_path):
            with open(self.map_path, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
            self.maps = data.get("maps", []) or []
            self.updated_at = data.get("updated_at", "") or ""
        else:
            logging.warning(f"缺少职业大典映射: {self.map_path}")

        self._reindex()

    def _reindex(self) -> None:
        self._by_code = {o.get("code"): o for o in self.occupations if o.get("code")}
        self._map_by_occ: Dict[str, dict] = {}
        for m in self.maps:
            key = m.get("occur_id") or ""
            if key and key not in self._map_by_occ:
                self._map_by_occ[key] = m

    # ------------------------------------------------------------- queries
    def entry(self, code: str) -> Optional[dict]:
        """按细类编码取大典条目。"""
        return self._by_code.get(code)

    def gb_code_of(self, occur_id: str) -> str:
        """我们职业的 id → 大典细类编码；未映射返回空串。"""
        m = self._map_by_occ.get(occur_id)
        return (m or {}).get("gb_code") or ""

    def map_of(self, occur_id: str) -> Optional[dict]:
        return self._map_by_occ.get(occur_id)

    def path_of(self, code: str) -> str:
        """编码 → "大类 / 中类 / 小类" 中文路径，供人读。"""
        e = self.entry(code)
        if not e:
            return ""
        names = []
        for level, idx in (("major", self.categories),
                           ("middle", self.middles),
                           ("minor", self.minors)):
            key = e.get(level, "")
            hit = next((x for x in idx if x.get("code") == key), None)
            names.append(hit["name"] if hit else key)
        return " / ".join(names)

    def search(self, keyword: str, limit: int = 20) -> List[dict]:
        """按关键词在细类职业名里找（大典侧查表补全用）。"""
        kw = (keyword or "").strip()
        if not kw:
            return []
        hits = [o for o in self.occupations if kw in (o.get("name") or "")]
        return hits[:limit] if limit else hits

    def children_of(self, minor_code: str) -> List[dict]:
        return [o for o in self.occupations if o.get("minor") == minor_code]

    def by_major(self, major_code: str) -> List[dict]:
        return [o for o in self.occupations if o.get("major") == major_code]

    def digital_occupations(self) -> List[dict]:
        return [o for o in self.occupations if "S" in (o.get("marks") or [])]

    def green_occupations(self) -> List[dict]:
        return [o for o in self.occupations if "L" in (o.get("marks") or [])]

    # ------------------------------------------------------------- compute
    def coverage(self, industry_occ_ids: Optional[List[str]] = None) -> dict:
        """大典侧覆盖快照。

        industry_occ_ids 传职业库的全量 id，用来算"我们挂了多少"；
        不传则只报大典自身的规模。
        """
        total = len(self.occupations)
        ids = industry_occ_ids or []
        mapped = [i for i in ids if self.gb_code_of(i)]
        codes = {self.gb_code_of(i) for i in mapped}
        covered = [o for o in self.occupations if o.get("code") in codes]

        by_major = []
        for c in self.categories:
            sub = self.by_major(c.get("code", ""))
            hit = sum(1 for o in sub if o.get("code") in codes)
            by_major.append({
                "code": c.get("code", ""),
                "name": c.get("name", ""),
                "total": len(sub),
                "linked": hit,
            })

        return {
            "version": self.version,
            "updated_at": self.updated_at,
            "catalog_stats": self.stats,
            "total_catalog_occupations": total,
            "industry_occupations": len(ids),
            "mapped_occupations": len(mapped),
            "map_rate": (len(mapped) / len(ids)) if ids else 0.0,
            "catalog_codes_covered": len(codes),
            "catalog_coverage": (len(codes) / total) if total else 0.0,
            "digital_total": len(self.digital_occupations()),
            "digital_covered": sum(1 for o in covered if "S" in (o.get("marks") or [])),
            "green_total": len(self.green_occupations()),
            "green_covered": sum(1 for o in covered if "L" in (o.get("marks") or [])),
            "by_major": by_major,
        }

    def unmapped_gaps(self, industry_occ_ids: Optional[List[str]] = None,
                      major: str = "", limit: int = 0) -> List[dict]:
        """还没被我们的职业挂上的大典细类（补全缺口时的候选池）。

        注意：大典细类里有大量不会单独建数字员工单元的职业（军队人员、采矿工种），
        这份清单是**候选**，不是待办。但"不建单元"和"不登记"是两件事：
        该登记进职业库的（有雇主、有作业流程、有人群规模）就该登记，
        由 access 说明承接通道、由分区 status 回答要不要建单元。
        """
        ids = industry_occ_ids or []
        codes = {self.gb_code_of(i) for i in ids if self.gb_code_of(i)}
        rows = [o for o in self.occupations if o.get("code") not in codes]
        if major:
            rows = [o for o in rows if o.get("major") == major]
        return rows[:limit] if limit else rows

    # ------------------------------------------------------------ validate
    def validate(self, industry_occ_ids: Optional[List[str]] = None) -> List[str]:
        """映射与目录的自检，返回问题列表，空表示健康。

        1. 目录规模与 stats 自述一致（防止手工改数据后 stats 变成谎话）
        2. 细类 code 唯一非空，且 major/middle/minor 父级真实存在
        3. 映射的 gb_code 必须真实存在于目录
        4. 映射的 occur_id 必须真实存在于职业库（悬空外键 = 职业改名后没同步）
        5. 一个 occur_id 只能挂一条映射（重复会让 gb_code_of 静默取首条）
        """
        problems: List[str] = []
        if not self.occupations:
            problems.append(f"未读到大典目录: {self.catalog_path}（参考表缺失，自检不能视为通过）")
            return problems

        stats = self.stats or {}
        for key, actual in (("categories", len(self.categories)),
                            ("middles", len(self.middles)),
                            ("minors", len(self.minors)),
                            ("occupations", len(self.occupations))):
            if key in stats and stats[key] != actual:
                problems.append(f"大典 stats.{key} 声明 {stats[key]}，实际 {actual}")

        seen: Dict[str, int] = {}
        cat_codes = {c.get("code") for c in self.categories}
        mid_codes = {m.get("code") for m in self.middles}
        min_codes = {m.get("code") for m in self.minors}
        for o in self.occupations:
            code = o.get("code") or ""
            if not code:
                problems.append("大典存在缺 code 的细类条目")
                continue
            seen[code] = seen.get(code, 0) + 1
            if o.get("major") not in cat_codes:
                problems.append(f"大典 {code} 的 major={o.get('major')} 不是合法大类")
            if o.get("middle") not in mid_codes:
                problems.append(f"大典 {code} 的 middle={o.get('middle')} 不是合法中类")
            if o.get("minor") not in min_codes:
                problems.append(f"大典 {code} 的 minor={o.get('minor')} 不是合法小类")
        for code, n in seen.items():
            if n > 1:
                problems.append(f"大典细类 code 重复: {code} 出现 {n} 次")

        dup: Dict[str, int] = {}
        for m in self.maps:
            key = m.get("occur_id") or ""
            gb = m.get("gb_code") or ""
            dup[key] = dup.get(key, 0) + 1
            if not key:
                problems.append("映射存在缺 occur_id 的条目")
                continue
            if not gb:
                problems.append(f"映射 {key} 未填 gb_code")
            elif gb not in self._by_code:
                problems.append(f"映射 {key} 的 gb_code={gb} 不在大典目录中")
            conf = m.get("confidence")
            if conf not in ("exact", "near"):
                problems.append(f"映射 {key} 的 confidence={conf!r} 非法（exact/near）")
            if industry_occ_ids and key not in industry_occ_ids:
                problems.append(
                    f"映射 {key} 指向不存在的职业（职业改名/删除后未同步映射）")
        for key, n in dup.items():
            if key and n > 1:
                problems.append(f"映射 occur_id 重复: {key} 出现 {n} 次（gb_code_of 会静默取首条）")
        return problems

    # ------------------------------------------------------------- render
    def render_coverage(self, industry_occ_ids: Optional[List[str]]) -> str:
        s = self.coverage(industry_occ_ids)
        st = s["catalog_stats"] or {}
        lines = [
            "=" * 72,
            f"职业分类大典（{s['version']} 年版）· 参考表覆盖",
            "-" * 72,
            f"大典规模: {st.get('categories', '-')} 大类 / {st.get('middles', '-')} 中类 / "
            f"{st.get('minors', '-')} 小类 / {s['total_catalog_occupations']} 细类职业",
            f"职业库映射: {s['mapped_occupations']}/{s['industry_occupations']} "
            f"({s['map_rate']:.1%}) 已挂 gb_code",
            f"大典覆盖: {s['catalog_codes_covered']}/{s['total_catalog_occupations']} "
            f"({s['catalog_coverage']:.1%}) 细类已被某个行业职业挂上",
            f"数字职业 S: {s['digital_covered']}/{s['digital_total']}   "
            f"绿色职业 L: {s['green_covered']}/{s['green_total']}",
            "-" * 72,
            f"{'大类':<4}{'名称':<34}{'已挂':>5}{'细类':>6}",
        ]
        for r in s["by_major"]:
            lines.append(f"{r['code']:<6}{r['name'][:30]:<32}{r['linked']:>5}{r['total']:>7}")
        lines.append("-" * 72)
        lines.append("注: 大典覆盖天然偏低——军队人员/采矿工种等细类不会单独建数字员工单元，")
        lines.append("    这个数字表示「还剩多少可选」，不是「还差多少要补」。")
        lines.append("=" * 72)
        return "\n".join(lines)
