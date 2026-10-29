"""M11 行业分区定义库 · industry-db

设计立场（2026-10 用户拍板后改版）：

- **岗位原子化**：occupation 是最小单目标，带唯一编号 ``code``（OCC-000001）。
  它**不存归属字段**——"我在哪个分区"不写在职业身上。
- **归属模糊化**：partition 只是"一种看法"。一个职业可以同时落在任意多个
  分区里、各有各的权重（0.7/0.2/0.1），也允许同时落在同一根轴的多个视角里。
  分类是**筛选器**，不是户籍；不追求"确定的单一归属"，因为现实里本来没有。
- 因此 data/industry-partitions.yaml 不存成员清单，data/industry-occupations.yaml
  不存 unit_id；两者之间的边单独放在 data/occupation-memberships.yaml
  （由 occupation.profile 派生，见 engine/occupation_axis.py）。
- 覆盖口径拆成两个，别混读：
    * 登记完整率 = 有唯一编号且在册的职业数 / 在册职业数（恒 100%，防漏登）
    * 分区覆盖 = 已建单元的分区数 / (covered + pending) 分区数
    * 归属边数**不是**覆盖率的分母：一个职业挂三个分区不代表覆盖变好。
- ``status`` 只回答"要不要建数字员工单元"，**不回答"这个职业是否存在、值不值得分析"**：
  evaluated（评估后不建单元）分区的职业照样登记、照样进画像与统计。

兼容：旧的单值 ``occupation.unit_id`` 仍被识别（推成一条 weight=1 的边），
但它是"这份数据以前只有这一个说法"，不再代表"只能属于这里"。
"""
from __future__ import annotations

import logging
import os
import unicodedata
from typing import Dict, List, Optional

import yaml

from .global_framework import ClassificationSources, IscoCatalog
from .occupation_axis import AXES as OCC_AXES, OccupationAxis
from .occupation_catalog import OccupationCatalog
from .registry import Registry

# 参与"应建设"分母的分区状态；evaluated 表示评估后明确不建单元
_BUILDABLE = ("covered", "pending")
# 合法状态全集：拼错/漏填的分区既不进分母也不报错，覆盖会静默变好看
_STATUSES = ("covered", "pending", "evaluated")

# 需求侧承接通道（occupation.access）。**只回答"怎么和付费方接上"，
# 不回答"值不值得分析"** —— 后者由 status / 覆盖率各自回答。
#   paid_direct  服务本身在市场上直接收费（缺省值，老数据不用回填）
#   non_market   财政/公共预算供养，终端用户不直接付费（军人/消防/政务窗口）
#   org_internal 企业内部职能（行政/前台/薪酬核算），需求侧是雇主预算
#   household    家庭内部无酬劳动（家务/照护家人），无现金交易
ACCESS_SIDES = ("paid_direct", "non_market", "org_internal", "household")
# 缺省即现金市场直连：字段不写 = paid_direct，避免为 139 条老数据补字段
DEFAULT_ACCESS = "paid_direct"

# 四根轴（与 global_framework.AXES 对齐）。分区缺省即四轴都可看。
AXES = ("occupation", "industry", "tax", "output")


class IndustryDatabase:
    """行业分区定义库：occupation（最小单位）+ partition（聚类结果）。"""

    def __init__(self, data_dir: Optional[str] = None,
                 registry: Optional[Registry] = None):
        self.data_dir = data_dir or self._find_data_dir()
        self.registry = registry or Registry()
        # 大典参考表：只读旁证。缺失时降级为 None，映射率一类统计自动归零，
        # 不让"没下参考表"把整个行业库变成不可用。
        self.catalog: Optional[OccupationCatalog] = None
        try:
            self.catalog = OccupationCatalog(self.data_dir)
        except Exception as exc:  # noqa: BLE001 - 参考表坏掉不该拖垮主库
            logging.warning(f"职业大典参考表加载失败，相关统计降级: {exc}")
        # 全球分类框架：ISCO-08 只读参考表 + 四根轴索引。同样降级不阻断主库，
        # 但缺失/写错会进 validate() 的 problems（旁证坏了比没有旁证更坏）。
        self.isco: Optional[IscoCatalog] = IscoCatalog(os.path.join(
            self.data_dir, "reference"))
        self.classification_sources: Optional[ClassificationSources] = \
            ClassificationSources(os.path.join(self.data_dir, "reference"))
        self.occ_path = os.path.join(self.data_dir, "industry-occupations.yaml")
        self.part_path = os.path.join(self.data_dir, "industry-partitions.yaml")
        # 归属边（occupation × partition × axis）。缺失不报错：老数据仍能用
        # occupation.unit_id 单值推出等价的一条边，别让"没这个文件"变成不可用。
        self.member_path = os.path.join(self.data_dir, "occupation-memberships.yaml")
        self.version = "0.1"
        self.updated_at = ""
        self.occupations: List[dict] = []
        self.partitions: List[dict] = []
        self._memberships_raw: List[dict] = []
        self._load()

    # ---------------------------------------------------------------- load
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
        """读两个数据文件；缺失时降级为空库，compute() 仍可稳定返回。"""
        if os.path.exists(self.occ_path):
            with open(self.occ_path, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
            self.occupations = data.get("occupations", []) or []
            self.version = data.get("version", self.version) or self.version
            self.updated_at = data.get("updated_at", "") or ""
        else:
            logging.warning(f"缺少职业清单: {self.occ_path}")

        if os.path.exists(self.part_path):
            with open(self.part_path, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
            self.partitions = data.get("partitions", []) or []
        else:
            logging.warning(f"缺少分区清单: {self.part_path}")

        if os.path.exists(self.member_path):
            with open(self.member_path, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
            rows = data.get("memberships")
            # 没有 memberships 段就当作"没写这张表"，交给 profile 派生
            self._memberships_raw = rows if isinstance(rows, list) else []

        self._reindex()

    def _reindex(self) -> None:
        """按当前列表重建 id 索引（显式保留首次出现，不依赖 dict 覆盖顺序）。

        校验/查询前会按列表指纹检查一次：有人 append 了分区或替换了某条记录时
        自动重建，避免拿加载期索引去判断已被改动过的数据（会误判"悬空"，
        也会让 partition() 返回旧对象）。
        """
        self._occ_by_id = self._index(self.occupations, "职业")
        self._part_by_id = self._index(self.partitions, "分区")
        # 软归属视图：职业↔分区的边一律由它给出，成员反查不再读单值字段。
        # 已有视图时先固化"当前生效的边"（profile 派生与显式边可能混用，
        # 直接拿 _memberships_raw 重建会把派生边丢掉）。
        prev = getattr(self, "axis_view", None)
        if prev is not None:
            self._memberships_raw = [dict(m) for m in prev.memberships]
        self.axis_view = OccupationAxis(self.occupations, self.partitions,
                                        self._memberships_raw)
        self._fingerprint = (len(self.occupations), len(self.partitions),
                             sum(id(o) for o in self.occupations),
                             sum(id(o) for o in self.partitions))

    @staticmethod
    def _index(rows: List[dict], label: str) -> Dict[str, dict]:
        """id -> 记录，重复 id 保留首次出现并告警（重复本身由 validate 报出）。"""
        index: Dict[str, dict] = {}
        for row in rows:
            key = row.get("id") or ""
            if not key:
                continue
            if key in index:
                logging.warning(f"{label} id 重复: {key}，索引保留首次出现的那条")
                continue
            index[key] = row
        return index

    def _ensure_fresh(self) -> None:
        """列表被外部改动过（增删/替换/换序）就重建索引。"""
        fp = (len(self.occupations), len(self.partitions),
              sum(id(o) for o in self.occupations),
              sum(id(o) for o in self.partitions))
        if fp != self._fingerprint:
            self._reindex()

    @staticmethod
    def _round_mix(dist: dict, keys) -> dict:
        """从实测分布里摘出指定键；n=0 时给三个 0，不伪装成"全部现金市场"。"""
        return {k: dist.get(k, 0.0) for k in keys}

    # ------------------------------------------------------------- queries
    def occupation(self, occ_id: str) -> Optional[dict]:
        self._ensure_fresh()
        return self._occ_by_id.get(occ_id)

    def partition(self, part_id: str) -> Optional[dict]:
        self._ensure_fresh()
        return self._part_by_id.get(part_id)

    def members_of(self, part_id: str, axis: str = "", min_weight: float = 0.0) -> List[dict]:
        """某视角下能看到的职业。

        注意**不是**"属于这个分区的职业"——归属是模糊的，这里给的是
        "按这个视角筛出来的结果"，同一个职业可以同时出现在别的视角里。
        同一分区内按 weight 降序；同职业在该视角下按最高权重去重（一个职业
        不会因为同轴挂了两个视角就在同一张表里出现两次以上）。
        """
        return self.axis_view.occupations_of(part_id, axis, min_weight)

    def weights_of(self, part_id: str, axis: str = "") -> Dict[str, float]:
        """视角内 职业 -> 权重（同轴同分区只保留最高权重，避免一条边被算两遍）。"""
        out: Dict[str, float] = {}
        for m in self.axis_view.of_partition(part_id, axis):
            occ = m.get("occupation", "")
            w = max(out.get(occ, 0.0), self.axis_view._weight(m))
            out[occ] = w
        return out

    def views_of_occupation(self, occ_id: str, axis: str = "",
                            min_weight: float = 0.0) -> List[dict]:
        """这个职业被哪些视角引用过（含权重），用来解释"为什么它出现在那里"。"""
        return self.axis_view.of_occupation(occ_id, axis, min_weight)

    def unassigned_occupations(self) -> List[dict]:
        """没有被任何视角引用的职业：不是缺口，是"还没被任何聚类看上"。"""
        return self.axis_view.free_occupations()

    def linked_occupations(self) -> List[dict]:
        """至少被一个真实分区引用的职业（去重）：供给结构与通道统计的分母。

        用集合而不是边数：一个职业挂三个分区，人还是一个人。
        指向不存在分区的边（悬空）不进分母，由 validate() 单独报错。
        """
        known = {p.get("id") for p in self.partitions if p.get("id")}
        ids = {m.get("occupation", "") for m in self.axis_view.memberships
               if m.get("partition") in known}
        return [o for o in self.occupations if o.get("id") in ids]

    def provider_distribution(self, occupations: Optional[List[dict]] = None) -> dict:
        """按职业自身的 provider 实测统计供给结构（不读分区手写值）。"""
        occs = self.linked_occupations() if occupations is None else occupations
        counts = {"ai": 0, "hybrid": 0, "human": 0}
        for o in occs:
            key = o.get("provider")
            if key in counts:
                counts[key] += 1
        n = sum(counts.values())
        if not n:  # 无数据就是无数据，不伪装成"纯人供给"
            return {"ai": 0.0, "hybrid": 0.0, "human": 0.0, "n": 0}
        mix = {k: round(v / n * 100, 1) for k, v in counts.items()}
        mix["n"] = n
        return mix

    @staticmethod
    def access_of(occupation: dict) -> str:
        """职业的需求侧承接通道；未填 = 现金市场直连（老数据不用回填）。"""
        value = (occupation or {}).get("access") or DEFAULT_ACCESS
        return value

    def access_distribution(self, occupations: Optional[List[dict]] = None) -> dict:
        """按职业 access 字段实测统计承接通道构成。

        与 provider_distribution 同一立场：只统计实测，不读分区手写值。
        这份分布回答的是"这份需求从哪条通道进来"，不是"谁该被忽略"——
        非市场和家庭无酬两类同样计入 n。
        """
        occs = self.linked_occupations() if occupations is None else occupations
        counts = {k: 0 for k in ACCESS_SIDES}
        for o in occs:
            key = self.access_of(o)
            if key in counts:
                counts[key] += 1
            else:  # 未知通道不静默丢弃，按默认通道记并由 validate 报错
                counts[DEFAULT_ACCESS] += 1
        n = sum(counts.values())
        mix = {k: (round(v / n * 100, 1) if n else 0.0) for k, v in counts.items()}
        mix["n"] = n
        return mix

    def by_access(self, access: str) -> List[dict]:
        want = access or DEFAULT_ACCESS
        return [o for o in self.occupations if self.access_of(o) == want]

    def axes_of(self, partition: dict) -> List[str]:
        """分区在哪些轴上成立；缺省 = 四轴都可看（老数据不用回填）。"""
        axes = (partition or {}).get("axes") or list(AXES)
        return [a for a in axes if a in AXES]

    def by_axis(self, axis: str = "") -> List[dict]:
        """按视角取分区：同一个分区可以同时出现在多根轴下。"""
        if not axis:
            return list(self.partitions)
        return [p for p in self.partitions if axis in self.axes_of(p)]

    def by_provider(self, provider: str) -> List[dict]:
        return [o for o in self.occupations if o.get("provider") == provider]

    def by_billing(self, billing: str) -> List[dict]:
        return [o for o in self.occupations if o.get("billing") == billing]

    # ------------------------------------------------------------ compute
    def compute(self) -> dict:
        """分区/职业覆盖与产值聚合。"""
        buildable = [p for p in self.partitions if p.get("status") in _BUILDABLE]
        covered_parts = [p for p in buildable if p.get("status") == "covered"]

        baseline_occs = [o for o in self.occupations if o.get("baseline_occupation")]
        # 分母是"在册基线职业"，分子是"至少被一个真实视角引用过的基线职业"。
        # 注意归属是模糊的：这里只问"有没有被看见"，不问"归谁"。
        known_parts = {p.get("id") for p in self.partitions if p.get("id")}
        referred = {m.get("occupation") for m in self.axis_view.memberships
                    if m.get("partition") in known_parts}
        linked_baseline = [o for o in baseline_occs if o.get("id") in referred]

        # 产值只统计"有市场口径"的分区；None 表示刻意留空，不当作 0 参与排序
        gdp_known = [p for p in self.partitions if p.get("gdp_cny")]
        gdp_total = sum(p.get("gdp_cny") or 0 for p in self.partitions)
        gdp_covered = sum(p.get("gdp_cny") or 0 for p in self.partitions
                          if p.get("status") == "covered")

        # 供给结构：一律由成员职业的 provider 实测得出，与「不存第二份清单」一致。
        # 分区手写的 provider_mix 只作对账留档（provider_mix_declared），不参与展示。
        mix_n = self.provider_distribution()
        provider_mix = {k: mix_n[k] for k in ("ai", "hybrid", "human")}
        # 承接通道：与供给结构并列的另一维，回答"需求从哪条路进来"
        access_n = self.access_distribution()
        access_mix = {k: access_n[k] for k in ACCESS_SIDES}

        # 产出轴的就业口径：有人没产值（军队/家庭无酬）也算就业，
        # "多少人吃饭"本身就是市场画像，不能因为没有 gdp 就一起丢掉。
        emp_known = [p for p in self.partitions if p.get("employment") is not None]
        employment_total = sum(p.get("employment") or 0 for p in self.partitions)

        # 软归属统计：边数 ≠ 职业数。一个职业挂三个视角，人还是一个。
        total_edges = len(self.axis_view.memberships)
        multi_view = [o for o in self.occupations
                      if len({m.get("partition") for m in
                              self.axis_view.of_occupation(o.get("id", ""))}) > 1]
        free_occs = self.axis_view.free_occupations()

        rows = []
        for p in self.partitions:
            members = self.members_of(p.get("id", ""))
            _measured = self.provider_distribution(members)
            rows.append({
                "id": p.get("id", ""),
                "name": p.get("name", ""),
                "aliases": p.get("aliases", []) or [],
                "cluster_basis": p.get("cluster_basis", []) or [],
                "demand_side": p.get("demand_side", []) or [],
                "provider_mix": {k: v for k, v in
                                 _measured.items() if k != "n"},
                "provider_mix_n": _measured["n"],
                "provider_mix_declared": p.get("provider_mix", {}) or {},
                "provider_mix_estimated": p.get("provider_mix_estimated", {}) or {},
                "gdp_cny": p.get("gdp_cny"),
                "gdp_scope": p.get("gdp_scope", ""),
                "gdp_source": p.get("gdp_source", ""),
                "employment": p.get("employment"),
                "employment_source": p.get("employment_source", ""),
                "access_mix": self._round_mix(
                    self.access_distribution(members), ACCESS_SIDES),
                "axes": self.axes_of(p),
                "unit_id": p.get("unit_id", "") or "",
                "priority": p.get("priority", ""),
                "channels": p.get("channels", []) or [],
                # 岗位命名骨架：待建分区专填。公开出来是为了让"这个分区准备建
                # 哪些岗位"可评审，而不是埋在设计思路里
                "planned_roles": p.get("planned_roles", []) or [],
                "status": p.get("status", ""),
                "members": [o.get("id") for o in members],
                # 权重是"这份看法有多重"，不是概率：不要把它当成归属的唯一答案
                "member_weights": {o.get("id"): self.weights_of(p.get("id", "")).get(
                    o.get("id"), 1.0) for o in members},
                "member_count": len(members),
                # 几维视角：这个分区在几根轴上被引用（同一分区可多轴成立）
                "axis_edges": self.axis_view.axis_mix(p.get("id", "")),
                # 分区挂的大典类目：成员职业的 gb_code 去掉细类后的中类前缀，
                # 用来看"这个分区大致落在大典哪几块"，不是权威归属。
                "gb_majors": sorted({self.catalog.gb_code_of(m.get("id", ""))[:1]
                                     for m in members
                                     if self.catalog and self.catalog.gb_code_of(m.get("id", ""))}),
                "note": p.get("note", ""),
            })
        rows.sort(key=lambda r: (-(r["gdp_cny"] or 0), r["name"]))

        # 大典口径：只做旁证，不参与覆盖率分子分母。
        # 两处数字说的不是一回事——映射率看"我们的职业名有没有国家标准锚点"，
        # 大典覆盖度看"标准里还剩多少细类可选"，后者天然很小。
        catalog_stat = {"available": False}
        if self.catalog is not None:
            ids = [o.get("id", "") for o in self.occupations if o.get("id")]
            cov = self.catalog.coverage(ids)
            catalog_stat = {
                "available": True,
                "version": cov["version"],
                "total_catalog_occupations": cov["total_catalog_occupations"],
                "mapped_occupations": cov["mapped_occupations"],
                "map_rate": cov["map_rate"],
                "catalog_codes_covered": cov["catalog_codes_covered"],
                "catalog_coverage": cov["catalog_coverage"],
                "digital_total": cov["digital_total"],
                "digital_covered": cov["digital_covered"],
                "green_total": cov["green_total"],
                "green_covered": cov["green_covered"],
                "by_major": cov["by_major"],
            }

        return {
            "version": self.version,
            "provider_mix_basis": "按已挂分区职业的 provider 字段实测",
            "updated_at": self.updated_at,
            "total_occupations": len(self.occupations),
            "baseline_occupations": len(baseline_occs),
            "linked_baseline_occupations": len(linked_baseline),
            "occupation_coverage": (len(linked_baseline) / len(baseline_occs))
                                   if baseline_occs else 0.0,
            "total_partitions": len(self.partitions),
            "buildable_partitions": len(buildable),
            "covered_partitions": len(covered_parts),
            "partition_coverage": (len(covered_parts) / len(buildable))
                                  if buildable else 0.0,
            "evaluated_partitions": sum(
                1 for p in self.partitions if p.get("status") == "evaluated"),
            "gdp_total_cny": gdp_total,
            "gdp_covered_cny": gdp_covered,
            "gdp_known_partitions": len(gdp_known),
            "provider_mix": provider_mix,
            "provider_mix_n": mix_n["n"],
            "access_mix": access_mix,
            "access_mix_n": access_n["n"],
            "access_sides": list(ACCESS_SIDES),
            "axes_present": list(AXES),
            "employment_total_wan": employment_total,
            # 软归属口径：边数、多视角职业数、未挂任何视角的职业数。
            # 这三个数只描述"看法有多少种"，不参与覆盖率分母。
            "membership_edges": total_edges,
            "multi_view_occupations": len(multi_view),
            "avg_views_per_occupation": (round(
                total_edges / len(self.occupations), 2)
                if self.occupations else 0.0),
            "free_occupations": len(free_occs),
            "occupation_axes_present": list(OCC_AXES),
            "employment_known_partitions": len(emp_known),
            "catalog": catalog_stat,
            "rows": rows,
        }

    # ------------------------------------------------------------- render
    def render_text(self, top: int = 0) -> str:
        s = self.compute()
        lines = [
            "=" * 72,
            f"行业分区定义库  v{s['version']}  updated {s['updated_at']}",
            "-" * 72,
            f"分区: {s['covered_partitions']}/{s['buildable_partitions']} 已建单元"
            f"  ({s['partition_coverage']:.1%})  另有 {s['evaluated_partitions']} 个"
            f"评估后不建单元(不计分母)",
            f"职业登记: {s['linked_baseline_occupations']}/{s['baseline_occupations']} 基线"
            f"  ({s['occupation_coverage']:.1%})  全量登记 {s['total_occupations']} 个"
            f"（登记完整 ≠ 单元建好，这是两个分母）",
            f"视角边: {s['membership_edges']} 条，被多个视角同时引用的岗位 "
            f"{s['multi_view_occupations']} 个，未被任何视角引用的 "
            f"{s['free_occupations']} 个（归属是模糊的：边数不是覆盖率，"
            f"也不是重复登记）",
            f"供给结构({s['provider_mix_n']} 个已挂分区职业 provider 实测): "
            f"AI {s['provider_mix']['ai']}% / 混合 {s['provider_mix']['hybrid']}% / "
            f"纯人 {s['provider_mix']['human']}%",
            f"承接通道({s['access_mix_n']} 个实测): "
            + " / ".join(f"{k} {s['access_mix'][k]}%" for k in ACCESS_SIDES)
            + f"   就业口径合计 {s['employment_total_wan']} 万人"
              f"（{s['employment_known_partitions']} 个分区有数）",
            "-" * 72,
            f"{'状态':<5}{'分区':<14}{'职业':<6}{'产值(亿元)':<12}{'AI%':<6}付费方",
        ]
        rows = s["rows"][:top] if top else s["rows"]
        for r in rows:
            mark = {"covered": "已建", "pending": "待建",
                    "evaluated": "不建"}.get(r["status"], r["status"])
            # _pad 按"显示宽度"补空格，字符数≠列数：'无口径' 是 3 字符 6 列，
            # '330,000' 是 7 字符 7 列，所以列宽要从字符数折算回来
            gdp = (f"{r['gdp_cny'] / 1e8:,.0f}" if r["gdp_cny"] else "无口径")
            # 无成员 = 无实测数据，用 "-" 区分"真实 0%"（如健康医疗 AI 0.0）
            ai = str("-" if r["member_count"] == 0
                     else (r["provider_mix"] or {}).get("ai", "-"))
            demand = "、".join(r["demand_side"])[:28]
            # 全列按显示宽度定宽：'{: <14}' 和 str.ljust 都按字符数算，
            # 中日韩字符占两列，中文名会把后面几列整体顶歪
            lines.append(self._cell(mark, 5) + self._cell(r["name"], 20)
                         + self._cell(r["member_count"], 8)
                         + self._cell(gdp, 10) + self._cell(ai, 7) + demand)
        lines.append("-" * 72)
        lines.append(f"有产值口径的分区 {s['gdp_known_partitions']}/{s['total_partitions']}，"
                     f"合计产值 {s['gdp_total_cny'] / 1e12:.1f} 万亿元(量级参考，"
                     f"非官方统计，含口径重叠)")
        lines.append("=" * 72)
        return "\n".join(lines)

    @staticmethod
    def _disp_width(text: str) -> int:
        """终端显示宽度：CJK 全角按 2 列算，避免中文名把列挤歪。"""
        return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
                   for ch in str(text))

    @classmethod
    def _pad(cls, text: str, width: int) -> str:
        """按显示宽度左对齐补空格（str.ljust 按字符数补，中文会错位）。"""
        text = str(text)
        return text + " " * max(0, width - cls._disp_width(text))

    @classmethod
    def _cell(cls, text: str, width: int) -> str:
        """定宽单元格：width 是**显示宽度**。

        `_pad(text, n)` 的 n 是宽度，但中文的字符数少于宽度，超宽时 strlen
        会先超过 n —— 所以先用 `_disp_width` 判断是否要截，再按"剩余宽度"
        补空格，别拿字符数当列数用。
        """
        text = str(text)
        if cls._disp_width(text) > width:
            truncated = ""
            for ch in text:
                if cls._disp_width(truncated + ch + "…") > width:
                    break
                truncated += ch
            text = truncated + "…"
        return text + " " * max(0, width - cls._disp_width(text))

    def gaps(self) -> List[dict]:
        return [r for r in self.compute()["rows"] if r["status"] == "pending"]

    # ------------------------------------------------------------ validate
    # 分区手写 provider_mix 与实测分布的允许偏差（百分点），超出即报漂移
    DECLARED_MIX_TOLERANCE = 25.0
    # 校验条数的唯一来源。README / 文档标题 / CLI 回执都读它 —— 之前这条数被手抄
    # 三份，抄成了 15/17/18 三个数，评审两轮都在纠这个。
    VALIDATE_CHECK_COUNT = 17

    @staticmethod
    def _as_float(value, default: float = 0.0) -> float:
        """宽松转数：脏数据（字符串/None/布尔）转成默认值，校验本身不能因数据烂而崩。"""
        if isinstance(value, bool):
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def validate(self) -> List[str]:
        """数据一致性自检：返回问题列表，空表示健康。

        校验点（编号与 docs/industry/industry-partition-db.md 的表格一一对应）：
        1. 主键唯一且非空：职业/分区的 id 为空或重复 → 报错（空 id 让分母虚增，
           重复 id 让成员被静默丢弃、覆盖率一起失明）。职业还必须有唯一编号
           code（OCC-####），缺了就无法跨表对齐。
        2. 分区 status 必须在 _STATUSES 里：拼错/漏填的分区既不进分母也不报错，
           覆盖率会静默变好看。
        3. 职业 unit_id 必须指向已注册单元或已知分区（悬空即脏数据，既不进
           覆盖率分子也不进供给结构分母）。
        4. 分区 covered 必须有 unit_id。
        5. 分区 unit_id 必须已注册。
        6. 分区 covered 必须有成员职业（纸面覆盖：数值上不失真，但该行业岗位
           其实没登记）。
        7. evaluated（评估后明确不建单元）不得带 unit_id → 状态互斥。
        8. 归属边只能指向真实存在的分区，且同一 (职业,分区,轴) 不得重复；
           weight 必须落在 (0,1]（写 0 只会制造噪音，不想归属就别写这条边）。
           旧数据里 occupation.unit_id 挂到单元 id 而非分区 id 的情形，
           按"单元名=分区名是缺省"识别，不硬报错——同一个名字不会因为
           多贴了一个标签就变成另一种东西。
        9. 已建单元的分区成员必须填 unit_role（否则路由永远命中不了）。
        10. 未建单元的成员 unit_role 可空，但填了必须在该分区 planned_roles 里。
        11. 声明 provider_mix 与实测偏差 > DECLARED_MIX_TOLERANCE → 报漂移；
            无成员分区 provider_mix 必须 0/0/0（估算值放 provider_mix_estimated）。
        12. 注册单元的每个 role 都要在职业库有登记。
        13. 数据文件缺失：空库必须显式报出，不能 0 分区 0 职业还"自检通过"。
        14. 大典映射自洽：gb_code 必须真实存在于大典目录，映射的 occur_id 必须
            真实存在于职业库（职业改名后映射会悬空，gb_code_of 静默返回空串）。
            参考表整体缺失时单独报一条，不假装"没有映射所以没问题"。
        15. 职业 access 必须落在 ACCESS_SIDES 里：写错（比如 non-market 带连字符）
            会静默落回 paid_direct，把"财政供养"念成"现金市场"，通道结构直接失真。
        16. 分区 axes 必须是 AXES 子集且非空：写错等于这个分区在所有视角里都消失，
            而覆盖率不会因此变红半格。
        17. 分区 employment 若填了必须是非负数值；0 与"没口径"不是一回事，
            没口径请留空（null），别填 0 冒充实测。
        """
        problems: List[str] = []
        self._ensure_fresh()
        # 归属视图跟着列表/边一起刷新：validate 必须看"当前数据"，
        # 不能拿加载期快照判悬空（那会让构造出来的脏数据静默通过）
        self._memberships_raw = [dict(m) for m in self.axis_view.memberships]
        self.axis_view = OccupationAxis(self.occupations, self.partitions,
                                        self._memberships_raw)

        # 13. 数据源可用：yaml 缺失时不能静默当"健康空库"
        for path, label in ((self.occ_path, "职业清单"),
                            (self.part_path, "分区清单")):
            if not os.path.exists(path):
                problems.append(f"未读到{label}: {path}（数据源缺失，自检不能视为通过）")

        # 1. 主键唯一 + 非空
        problems.extend(self._check_primary_keys())

        # 2. 状态枚举
        for p in self.partitions:
            status = p.get("status")
            if status not in _STATUSES:
                problems.append(
                    f"分区 {p.get('id') or '(空)'} 的 status={status!r} 不在合法状态 "
                    f"{list(_STATUSES)} 中（拼错/漏填会让该分区静默漏出分母）")

        unit_ids = {u.unit_id for u in self.registry.all_units()}
        # 分区集合按当前列表现算：加载期索引会因追加/改动而过期
        part_by_id = {x.get("id", ""): x for x in self.partitions if x.get("id")}

        # 3. 旧单值 unit_id 的存在性（只对"没有 profile 的老数据"生效，
        # 软归属的边由第 8 条统一校验，两条路不重复报）
        for o in self.occupations:
            if o.get("profile"):
                continue
            uid = o.get("unit_id") or ""
            if not uid:
                continue  # 没有任何视角引用是允许的：原子岗位不靠归属活着
            if uid not in unit_ids and uid not in part_by_id:
                problems.append(
                    f"职业 {o.get('id')} 的 unit_id={uid} "
                    f"既不是已注册单元也不是已知分区")

        for p in self.partitions:
            pid = p.get("id", "")
            uid = p.get("unit_id", "") or ""
            status = p.get("status", "")
            members = self.members_of(pid)

            # 7. 状态互斥
            if status == "evaluated" and uid:
                problems.append(
                    f"分区 {pid} 标记 evaluated(不建单元) 却填了 unit_id={uid}，语义矛盾")
            # 4. covered 必须有 unit_id
            if status == "covered" and not uid:
                problems.append(f"分区 {pid} 标记 covered 但未填 unit_id")
            # 5. unit_id 必须已注册
            if uid and uid not in unit_ids:
                problems.append(f"分区 {pid} 的 unit_id={uid} 未注册")
            # 6. covered 却无成员 → 纸面覆盖
            if status == "covered" and not members:
                problems.append(
                    f"分区 {pid} 标记 covered 但职业库无成员职业"
                    f"（纸面覆盖：需先登记该分区职业并标 baseline_occupation）")

            unit = self.registry.get_unit(uid) if uid else None
            planned = set(p.get("planned_roles", []) or [])
            # 岗位名现在挂在**边上**（membership.unit_role），不在职业身上：
            # 一个职业在两处干活，两处的岗位名本来就该不同。
            role_edge = {m.get("occupation"): m.get("unit_role") or ""
                         for m in self.axis_view.of_partition(pid)}
            for o in members:
                role = role_edge.get(o.get("id"), "")
                if unit is None:
                    # 10. 未建单元：unit_role 可空，填了必须落在 planned_roles 骨架里
                    if role and planned and role not in planned:
                        problems.append(
                            f"职业 {o.get('id')} 的 unit_role={role} 不在分区 "
                            f"{pid} 的 planned_roles 中 {sorted(planned)}")
                    continue
                # 9. 已建单元必须填 unit_role
                if not role:
                    problems.append(
                        f"职业 {o.get('id')} 挂在已注册单元 {unit.unit_id}，"
                        f"但未填 unit_role（建单元后路由命中不了该岗位）")
                    continue
                role_names = {r.name for r in unit.roles}
                if role not in role_names:
                    problems.append(
                        f"职业 {o.get('id')} 的 unit_role={role} "
                        f"不在单元 {unit.unit_id} 的岗位中 {sorted(role_names)}")

            # 11. 声明值 vs 实测 对账
            declared = p.get("provider_mix") or {}
            if not members:
                if any(self._as_float(declared.get(k)) for k in
                       ("ai", "hybrid", "human")):
                    problems.append(
                        f"分区 {pid} 无成员职业，provider_mix(实测口径) 应为 "
                        f"0/0/0，实际 {declared}（估算值请放 provider_mix_estimated）")
            elif declared:
                measured = self.provider_distribution(members)
                for k in ("ai", "hybrid", "human"):
                    if k not in declared:
                        continue
                    drift = abs(self._as_float(declared.get(k)) - measured[k])
                    if drift > self.DECLARED_MIX_TOLERANCE:
                        problems.append(
                            f"分区 {pid} 的 provider_mix.{k} 声明 "
                            f"{declared.get(k)}% 与实测 {measured[k]}% "
                            f"偏差 {drift:.0f}pt（>{self.DECLARED_MIX_TOLERANCE:.0f}pt）")

        # 8. 软归属的边自检（悬空分区/未知轴/权重越界/同边重复/唯一编号）。
        # 老单值 unit_id 挂到"单元 id"的情形在这里不再报错：单元名与分区名同名
        # 是缺省约定，同一个名字不该因为多贴了个标签就被判成错挂。
        problems.extend(self.axis_view.validate())

        # 12. 注册单元的每个 role 都要有职业在该单元名下认领（按边查，不按字段）
        claimed = {(m.get("partition"), m.get("unit_role"))
                   for m in self.axis_view.memberships if m.get("unit_role")}
        for unit in self.registry.all_units():
            for role in unit.roles:
                if (unit.unit_id, role.name) not in claimed:
                    problems.append(
                        f"单元 {unit.unit_id} 的岗位 {role.name} 未在职业库登记"
                        f"（需要在 occupation-memberships.yaml 里有一条带该 unit_role 的边）")

        # 14. 大典映射自洽：参考表是旁证，但旁证错了比没有更坏
        if self.catalog is None:
            problems.append(
                "职业大典参考表未加载（data/reference/），gb_code 映射无法校验")
        else:
            ids = [o.get("id", "") for o in self.occupations if o.get("id")]
            problems.extend(self.catalog.validate(ids))

        # 15. 承接通道枚举（写错会静默落回 paid_direct）
        for o in self.occupations:
            raw = o.get("access")
            if raw is not None and raw not in ACCESS_SIDES:
                problems.append(
                    f"职业 {o.get('id')} 的 access={raw!r} 不在合法通道 "
                    f"{list(ACCESS_SIDES)} 中（写错会被静默当成 {DEFAULT_ACCESS}）")

        # 16/17. 分区视角与就业口径
        for p in self.partitions:
            pid = p.get("id") or "(空)"
            axes = p.get("axes")
            if axes is not None:
                bad = [a for a in axes if a not in AXES]
                if bad:
                    problems.append(
                        f"分区 {pid} 的 axes 含未知轴 {bad}（合法 {list(AXES)}）")
                elif not axes:
                    problems.append(
                        f"分区 {pid} 的 axes 为空（空视角 = 任何看板都查不到它）")
            emp = p.get("employment")
            if emp is not None:
                if isinstance(emp, bool) or not isinstance(emp, (int, float)) or emp < 0:
                    problems.append(
                        f"分区 {pid} 的 employment={emp!r} 不是非负数"
                        f"（没口径请留空，别填 0 冒充实测）")

        # 18. 全球分类框架（ISCO-08 参考表 + 四根轴索引）
        if self.isco is not None:
            problems.extend(self.isco.validate())
        if self.classification_sources is not None:
            problems.extend(self.classification_sources.validate())
        return problems

    def _check_primary_keys(self) -> List[str]:
        """1. 主键唯一且非空。空 id 会让分子分母一起虚增；重复 id 会让成员被
        静默丢弃（index 只留首次出现），覆盖率与供给结构一起缩水。"""
        problems: List[str] = []
        for rows, label in ((self.occupations, "职业"),
                            (self.partitions, "分区")):
            seen: Dict[str, List[int]] = {}
            for i, row in enumerate(rows, 1):
                key = row.get("id")
                if not key:
                    problems.append(
                        f"{label}第 {i} 条缺少 id（主键必填，空 id 会让分母虚增）")
                elif not str(key).strip():
                    problems.append(f"{label}第 {i} 条的 id 为空白（主键必填）")
                seen.setdefault(key or "", []).append(i)
            for key, positions in seen.items():
                if key and len(positions) > 1:
                    where = "、".join(str(x) for x in positions)
                    problems.append(
                        f"{label} id 重复: {key} 出现 {len(positions)} 次"
                        f"（第 {where} 条），主键必须唯一")
        return problems
