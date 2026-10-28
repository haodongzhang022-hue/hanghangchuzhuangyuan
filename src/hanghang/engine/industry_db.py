"""M11 行业分区定义库 · industry-db

设计立场：**职业(occupation) 是解耦的最小单目标，行业(partition) 是聚类结果。**

- 职业登记在 data/industry-occupations.yaml，主键 id 稳定，不受行业命名影响；
  职业通过单值 unit_id 挂到唯一分区（多归属暂不支持：需要扩成 partition_ids 并
  同步 members_of/validate/导出，本轮不做），因此"改行业名"不会导致职业缺漏。
- 分区登记在 data/industry-partitions.yaml，只记录"为什么把这批职业聚在一起"：
  聚类依据 / 付费方 / 供给结构 / 产值口径。members 由 occupation.unit_id 反查，
  分区自身不重复存职业名，避免两份清单分叉。
- 覆盖口径（与 coverage-target 互补）：
    * 职业覆盖率 = 已挂到注册单元的职业数 / 基线职业数
    * 分区覆盖率 = 已建单元的分区数 / (covered + pending) 分区数
    * evaluated 分区（评估后判定不建单元）不计入分母，避免永久缺口。

本模块只读数据，不做落盘；导出面向 CNB 制品库/知识库的扁平表由 CLI 负责。
"""
from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional

import yaml

from .global_framework import ClassificationSources, IscoCatalog
from .occupation_catalog import OccupationCatalog
from .registry import Registry

# 参与"应建设"分母的分区状态；evaluated 表示评估后明确不建单元
_BUILDABLE = ("covered", "pending")
# 合法状态全集：拼错/漏填的分区既不进分母也不报错，覆盖会静默变好看
_STATUSES = ("covered", "pending", "evaluated")


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
        self.version = "0.1"
        self.updated_at = ""
        self.occupations: List[dict] = []
        self.partitions: List[dict] = []
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

        self._reindex()

    def _reindex(self) -> None:
        """按当前列表重建 id 索引（显式保留首次出现，不依赖 dict 覆盖顺序）。

        校验/查询前会按列表指纹检查一次：有人 append 了分区或替换了某条记录时
        自动重建，避免拿加载期索引去判断已被改动过的数据（会误判"悬空"，
        也会让 partition() 返回旧对象）。
        """
        self._occ_by_id = self._index(self.occupations, "职业")
        self._part_by_id = self._index(self.partitions, "分区")
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

    # ------------------------------------------------------------- queries
    def occupation(self, occ_id: str) -> Optional[dict]:
        self._ensure_fresh()
        return self._occ_by_id.get(occ_id)

    def partition(self, part_id: str) -> Optional[dict]:
        self._ensure_fresh()
        return self._part_by_id.get(part_id)

    def members_of(self, part_id: str) -> List[dict]:
        """分区成员 = 通过 occupation.unit_id 反查的职业（聚类结果，非手写清单）。"""
        return [o for o in self.occupations if o.get("unit_id") == part_id]

    def unassigned_occupations(self) -> List[dict]:
        """尚未挂到任何分区的职业：既可能是缺口，也可能是刻意不归属的孤立职业。"""
        return [o for o in self.occupations if not o.get("unit_id")]

    def linked_occupations(self) -> List[dict]:
        """已挂到分区且分区真实存在的职业：供给结构与覆盖率的有效分母。

        unit_id 悬空的职业（分区不存在）不进分母，避免脏数据污染占比；
        这类数据由 validate() 单独报错。
        """
        known = {p.get("id") for p in self.partitions if p.get("id")}
        return [o for o in self.occupations
                if o.get("unit_id") and o.get("unit_id") in known]

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
        linked_baseline = [o for o in baseline_occs if o.get("unit_id")]

        # 产值只统计"有市场口径"的分区；None 表示刻意留空，不当作 0 参与排序
        gdp_known = [p for p in self.partitions if p.get("gdp_cny")]
        gdp_total = sum(p.get("gdp_cny") or 0 for p in self.partitions)
        gdp_covered = sum(p.get("gdp_cny") or 0 for p in self.partitions
                          if p.get("status") == "covered")

        # 供给结构：一律由成员职业的 provider 实测得出，与「不存第二份清单」一致。
        # 分区手写的 provider_mix 只作对账留档（provider_mix_declared），不参与展示。
        mix_n = self.provider_distribution()
        provider_mix = {k: mix_n[k] for k in ("ai", "hybrid", "human")}

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
                "unit_id": p.get("unit_id", "") or "",
                "priority": p.get("priority", ""),
                "channels": p.get("channels", []) or [],
                "status": p.get("status", ""),
                "members": [o.get("id") for o in members],
                "member_count": len(members),
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
            f"职业: {s['linked_baseline_occupations']}/{s['baseline_occupations']} 基线"
            f"  ({s['occupation_coverage']:.1%})  全量登记 {s['total_occupations']} 个",
            f"供给结构({s['provider_mix_n']} 个已挂分区职业 provider 实测): "
            f"AI {s['provider_mix']['ai']}% / 混合 {s['provider_mix']['hybrid']}% / "
            f"纯人 {s['provider_mix']['human']}%",
            "-" * 72,
            f"{'状态':<5}{'分区':<14}{'职业':<6}{'产值(亿元)':<12}{'AI%':<6}付费方",
        ]
        rows = s["rows"][:top] if top else s["rows"]
        for r in rows:
            mark = {"covered": "已建", "pending": "待建",
                    "evaluated": "不建"}.get(r["status"], r["status"])
            gdp = f"{r['gdp_cny'] / 1e8:,.0f}" if r["gdp_cny"] else "无口径"
            # 无成员 = 无实测数据，用 "-" 区分"真实 0%"（如健康医疗 AI 0.0）
            ai = ("-" if r["member_count"] == 0
                  else (r["provider_mix"] or {}).get("ai", "-"))
            demand = "、".join(r["demand_side"])[:28]
            lines.append(f"{mark:<5}{r['name']:<14}{r['member_count']:<8}"
                         f"{gdp:<14}{ai:<8}{demand}")
        lines.append("-" * 72)
        lines.append(f"有产值口径的分区 {s['gdp_known_partitions']}/{s['total_partitions']}，"
                     f"合计产值 {s['gdp_total_cny'] / 1e12:.1f} 万亿元(量级参考，"
                     f"非官方统计，含口径重叠)")
        lines.append("=" * 72)
        return "\n".join(lines)

    def gaps(self) -> List[dict]:
        return [r for r in self.compute()["rows"] if r["status"] == "pending"]

    # ------------------------------------------------------------ validate
    # 分区手写 provider_mix 与实测分布的允许偏差（百分点），超出即报漂移
    DECLARED_MIX_TOLERANCE = 25.0

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
           重复 id 让成员被静默丢弃、覆盖率一起失明）。
        2. 分区 status 必须在 _STATUSES 里：拼错/漏填的分区既不进分母也不报错，
           覆盖率会静默变好看。
        3. 职业 unit_id 必须指向已注册单元或已知分区（悬空即脏数据，既不进
           覆盖率分子也不进供给结构分母）。
        4. 分区 covered 必须有 unit_id。
        5. 分区 unit_id 必须已注册。
        6. 分区 covered 必须有成员职业（纸面覆盖：数值上不失真，但该行业岗位
           其实没登记）。
        7. evaluated（评估后明确不建单元）不得带 unit_id → 状态互斥。
        8. 成员职业挂靠的 id 必须是分区 id 或分区指向的单元，其它一律报错。
           注意反查口径：members_of(pid) 按 unit_id == pid 匹配，挂错的成员压根
           不出现在 members 里，所以这条要独立扫全量职业才看得见。
        9. 已建单元的分区成员必须填 unit_role（否则路由永远命中不了）。
        10. 未建单元的成员 unit_role 可空，但填了必须在该分区 planned_roles 里。
        11. 声明 provider_mix 与实测偏差 > DECLARED_MIX_TOLERANCE → 报漂移；
            无成员分区 provider_mix 必须 0/0/0（估算值放 provider_mix_estimated）。
        12. 注册单元的每个 role 都要在职业库有登记。
        13. 数据文件缺失：空库必须显式报出，不能 0 分区 0 职业还"自检通过"。
        14. 大典映射自洽：gb_code 必须真实存在于大典目录，映射的 occur_id 必须
            真实存在于职业库（职业改名后映射会悬空，gb_code_of 静默返回空串）。
            参考表整体缺失时单独报一条，不假装"没有映射所以没问题"。
        """
        problems: List[str] = []
        self._ensure_fresh()

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

        # 3. 职业 unit_id 存在性
        for o in self.occupations:
            uid = o.get("unit_id") or ""
            if not uid:
                continue  # 未挂分区是显式登记的缺口，不算错
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
            for o in members:
                o_uid = o.get("unit_id") or ""
                # 3 已报悬空，这里不重复刷屏
                if o_uid and o_uid not in unit_ids and o_uid not in part_by_id:
                    continue
                # 注：members_of 按 unit_id == pid 反查，走进这个循环的职业天然
                # o_uid == pid，"成员挂靠一致性"在这里判不出东西；真正会错挂的
                # 情形（挂到单元 id）由下面第 8 条独立扫描覆盖。
                role = o.get("unit_role")
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

        # 8. 独立扫全量职业：成员反查按 unit_id == 分区 id 匹配，挂到单元 id 或
        # 挂到"不指向该单元的分区"的职业都不会出现在 members 里，只在成员循环
        # 里查永远看不见这类错挂。
        for o in self.occupations:
            o_uid = o.get("unit_id") or ""
            if not o_uid or o_uid in part_by_id:
                continue  # 未挂 / 正常挂在分区上（含单元与分区同名的情形）
            if o_uid in unit_ids:
                problems.append(
                    f"职业 {o.get('id')} 的 unit_id={o_uid} 是注册单元 id 而非分区 id"
                    f"（成员反查按分区 id 匹配，挂单元会让该职业不属于任何分区）")
            # 悬空已由第 3 条报出，这里不重复

        # 12. 注册单元的每个 role 都应有登记职业
        occ_by_role = {(o.get("unit_id"), o.get("unit_role")): o
                       for o in self.occupations if o.get("unit_id")}
        for unit in self.registry.all_units():
            for role in unit.roles:
                if (unit.unit_id, role.name) not in occ_by_role:
                    problems.append(
                        f"单元 {unit.unit_id} 的岗位 {role.name} 未在职业库登记")

        # 14. 大典映射自洽：参考表是旁证，但旁证错了比没有更坏
        if self.catalog is None:
            problems.append(
                "职业大典参考表未加载（data/reference/），gb_code 映射无法校验")
        else:
            ids = [o.get("id", "") for o in self.occupations if o.get("id")]
            problems.extend(self.catalog.validate(ids))

        # 15. 全球分类框架（ISCO-08 参考表 + 四根轴索引）
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
