"""M11 行业分区定义库 · industry-db

设计立场：**职业(occupation) 是解耦的最小单目标，行业(partition) 是聚类结果。**

- 职业登记在 data/industry-occupations.yaml，主键 id 稳定，不受行业命名影响；
  同一职业可被多个分区引用，因此"改行业名"不会导致职业缺漏。
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

from .registry import Registry

# 参与"应建设"分母的分区状态；evaluated 表示评估后明确不建单元
_BUILDABLE = ("covered", "pending")


class IndustryDatabase:
    """行业分区定义库：occupation（最小单位）+ partition（聚类结果）。"""

    def __init__(self, data_dir: Optional[str] = None,
                 registry: Optional[Registry] = None):
        self.data_dir = data_dir or self._find_data_dir()
        self.registry = registry or Registry()
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

        self._occ_by_id: Dict[str, dict] = {
            o.get("id", ""): o for o in self.occupations if o.get("id")}
        self._part_by_id: Dict[str, dict] = {
            p.get("id", ""): p for p in self.partitions if p.get("id")}

    # ------------------------------------------------------------- queries
    def occupation(self, occ_id: str) -> Optional[dict]:
        return self._occ_by_id.get(occ_id)

    def partition(self, part_id: str) -> Optional[dict]:
        return self._part_by_id.get(part_id)

    def members_of(self, part_id: str) -> List[dict]:
        """分区成员 = 通过 occupation.unit_id 反查的职业（聚类结果，非手写清单）。"""
        return [o for o in self.occupations if o.get("unit_id") == part_id]

    def unassigned_occupations(self) -> List[dict]:
        """尚未挂到任何分区的职业：既可能是缺口，也可能是刻意不归属的孤立职业。"""
        return [o for o in self.occupations if not o.get("unit_id")]

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

        # 供给结构：按分区成员职业数加权（分区之间不按产值加权，避免大行业淹没小行业）
        provider_mix = {"ai": 0.0, "hybrid": 0.0, "human": 0.0}
        weighted = 0
        for p in self.partitions:
            mix = p.get("provider_mix") or {}
            n = len(self.members_of(p.get("id", ""))) or 0
            if not n:
                continue
            for k in provider_mix:
                provider_mix[k] += (mix.get(k) or 0) * n
            weighted += n
        if weighted:
            for k in provider_mix:
                provider_mix[k] = round(provider_mix[k] / weighted, 1)

        rows = []
        for p in self.partitions:
            members = self.members_of(p.get("id", ""))
            rows.append({
                "id": p.get("id", ""),
                "name": p.get("name", ""),
                "aliases": p.get("aliases", []) or [],
                "cluster_basis": p.get("cluster_basis", []) or [],
                "demand_side": p.get("demand_side", []) or [],
                "provider_mix": p.get("provider_mix", {}) or {},
                "gdp_cny": p.get("gdp_cny"),
                "gdp_scope": p.get("gdp_scope", ""),
                "gdp_source": p.get("gdp_source", ""),
                "unit_id": p.get("unit_id", "") or "",
                "priority": p.get("priority", ""),
                "channels": p.get("channels", []) or [],
                "status": p.get("status", ""),
                "members": [o.get("id") for o in members],
                "member_count": len(members),
                "note": p.get("note", ""),
            })
        rows.sort(key=lambda r: (-(r["gdp_cny"] or 0), r["name"]))

        return {
            "version": self.version,
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
            f"供给结构(按成员职业加权): AI {s['provider_mix']['ai']}% / "
            f"混合 {s['provider_mix']['hybrid']}% / 纯人 {s['provider_mix']['human']}%",
            "-" * 72,
            f"{'状态':<5}{'分区':<14}{'职业':<6}{'产值(亿元)':<12}{'AI%':<6}付费方",
        ]
        rows = s["rows"][:top] if top else s["rows"]
        for r in rows:
            mark = {"covered": "已建", "pending": "待建",
                    "evaluated": "不建"}.get(r["status"], r["status"])
            gdp = f"{r['gdp_cny'] / 1e8:,.0f}" if r["gdp_cny"] else "无口径"
            ai = (r["provider_mix"] or {}).get("ai", "-")
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
    def validate(self) -> List[str]:
        """数据一致性自检：返回问题列表，空表示健康。

        校验点：
        1. 分区 members 反查到的职业，其 unit_role 必须真实存在于注册单元（防止
           职业挂错单元 → 路由永远命中不了，形成"纸面覆盖"）。
        2. 已注册单元里的每个 role 都应能在职业库找到对应职业（防止新增岗位漏登记）。
        3. 分区 status=covered 但无 unit_id、或 unit_id 指向不存在的单元 → 报错。
        """
        problems: List[str] = []
        unit_ids = {u.unit_id for u in self.registry.all_units()}

        for p in self.partitions:
            pid, status = p.get("id", ""), p.get("status", "")
            uid = p.get("unit_id", "") or ""
            if status == "covered" and not uid:
                problems.append(f"分区 {pid} 标记 covered 但未填 unit_id")
            if uid and uid not in unit_ids:
                problems.append(f"分区 {pid} 的 unit_id={uid} 未注册")
            for o in self.members_of(pid):
                unit = self.registry.get_unit(uid) if uid else None
                if unit is None:
                    problems.append(
                        f"职业 {o.get('id')} 挂在未注册单元 {uid}")
                    continue
                role_names = {r.name for r in unit.roles}
                if o.get("unit_role") not in role_names:
                    problems.append(
                        f"职业 {o.get('id')} 的 unit_role={o.get('unit_role')} "
                        f"不在单元 {uid} 的岗位中 {sorted(role_names)}")

        # 注册单元的每个 role 都应有登记职业
        occ_by_role = {(o.get("unit_id"), o.get("unit_role")): o
                       for o in self.occupations if o.get("unit_id")}
        for unit in self.registry.all_units():
            for role in unit.roles:
                if (unit.unit_id, role.name) not in occ_by_role:
                    problems.append(
                        f"单元 {unit.unit_id} 的岗位 {role.name} 未在职业库登记")
        return problems
