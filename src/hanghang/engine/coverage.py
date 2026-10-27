"""行业岗位覆盖进度统计 · coverage

把「目标全集(coverage-target.yaml) 作为分母」与「已注册单元(unit-index /
industry-register) 作为分子」做比对，得到系统化的行业/岗位覆盖进度表。

数据驱动：目标全集由 data/coverage-target.yaml 声明，已覆盖行业通过行业名
与注册单元自动关联(无需改代码)。新增目标行业只需在 coverage-target.yaml 的
targets 追加一条声明即可纳入进度统计。

覆盖率口径：
- 行业覆盖率 = 已注册(registered) 目标行业数 / 目标行业总数
- 岗位覆盖率 = 已覆盖岗位数 / 目标岗位基线数
    * 已注册行业：优先取 M11 职业库里"已挂到该单元"的基线职业数
      （职业是最小单位，一个职业通过单值 unit_id 挂到唯一分区，不会被行业命名
      变化影响；多归属暂不支持）；职业库不可用时回落到该单元实际注册岗位数(roles)
    * 待覆盖行业：优先取职业库里该分区的基线职业数；
      职业库无登记时回落到 target_roles 声明的代表性岗位数

职业库(industry-occupations.yaml)是岗位基线的权威来源，coverage-target 只兜底。
"""
from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional

import yaml

from .registry import Registry


class CoverageTracker:
    """计算并汇报「目标全集 vs 当前覆盖」的行业/岗位覆盖率。"""

    def __init__(self, registry: Optional[Registry] = None,
                 data_dir: Optional[str] = None, industry_db=None):
        self.registry = registry or Registry()
        self.data_dir = data_dir or self._find_data_dir()
        # 延迟导入避免循环依赖：职业库是岗位基线的权威来源
        if industry_db is None:
            try:
                from .industry_db import IndustryDatabase
                industry_db = IndustryDatabase(data_dir=self.data_dir,
                                               registry=self.registry)
            except Exception as exc:  # 职业库不可用不应阻断覆盖统计
                logging.warning(f"职业库不可用，岗位基线回落 coverage-target: {exc}")
                industry_db = False
        self.industry_db = industry_db or None
        self.target_path = os.path.join(self.data_dir, "coverage-target.yaml")
        self.targets: List[dict] = []
        self.version: str = "0.1"
        self.updated_at: str = ""
        self._load_targets()

    # ------------------------------------------------------------------ load
    def _find_data_dir(self) -> str:
        """定位 data 目录：优先工作区 cwd，其次仓库相对位置。"""
        cands = [os.path.join(os.getcwd(), "data"),
                 os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "../../data")]
        for c in cands:
            if os.path.isdir(c):
                return os.path.abspath(c)
        return os.path.abspath(cands[0])

    def _load_targets(self) -> None:
        """读取目标全集清单 coverage-target.yaml（一次性读盘并缓存元数据）。

        文件缺失时优雅降级：targets 置空、元数据保持默认值，供 compute() 稳定
        返回空覆盖(total=0/coverage=0)，与构造函数降级语义一致，避免后续抛
        FileNotFoundError。
        """
        if not os.path.exists(self.target_path):
            logging.warning(f"缺少目标全集清单: {self.target_path}")
            return
        with open(self.target_path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        self.targets = data.get("targets", [])
        # 元数据缓存为实例属性，compute()/render_text() 直接复用，避免重复读盘
        self.version = data.get("version", "0.1") or "0.1"
        self.updated_at = data.get("updated_at", "") or ""

    # ------------------------------------------------------------- mapping
    def _registered_map(self) -> Dict[str, dict]:
        """把已注册单元按 行业名 -> 单元 建索引，供自动判定已覆盖。"""
        index: Dict[str, dict] = {}
        for unit in self.registry.all_units():
            index.setdefault(unit.industry, unit)
        return index

    def _occupation_baseline(self, partition_id: str) -> Optional[int]:
        """职业库中该分区的基线职业数；职业库不可用或未登记时返回 None。"""
        db = self.industry_db
        if not db or not partition_id:
            return None
        if db.partition(partition_id) is None:
            return None
        baseline = [o for o in db.members_of(partition_id)
                    if o.get("baseline_occupation")]
        return len(baseline) if baseline else None

    def _baseline_source(self, partition_id: str, has_unit: bool) -> str:
        """标注该行岗位基线取自哪里，兜底要可见、不静默。

        - ``occupation``  职业库基线（权威源）
        - ``unit_roles``  分区无任何职业登记 → 回落注册岗位数（可接受兜底）
        - ``target_roles`` 分区无职业登记 → 回落 coverage-target 手写岗位（可接受兜底）
        - ``stale``       分区有职业登记但全部非基线 → 权威源失效，需报 problems
        """
        db = self.industry_db
        if not db or not partition_id or db.partition(partition_id) is None:
            return "unit_roles" if has_unit else "target_roles"
        members = db.members_of(partition_id)
        if any(o.get("baseline_occupation") for o in members):
            return "occupation"
        if members:
            return "stale"
        return "unit_roles" if has_unit else "target_roles"

    # ------------------------------------------------------------ compute
    def compute(self) -> dict:
        """
        计算覆盖进度，返回结构化结果：
        {
          version, updated_at,
          total_industries, covered_industries, pending_industries,
          industry_coverage,                 # 浮点 0-1
          total_role_baseline, covered_roles, role_coverage,
          by_category: { 大类: {total, covered, industries:[...] } },
          rows: [ 每个目标行业一行: {id,name,category,status,covered,roles:{covered,total},channels,note} ],
        }
        """
        registered = self._registered_map()

        total = len(self.targets)
        covered_industry = 0
        covered_role_total = 0          # 分子：已覆盖岗位数
        role_baseline_total = 0         # 分母：目标岗位基线数
        by_category: Dict[str, dict] = {}
        rows: List[dict] = []
        problems: List[str] = []

        for t in self.targets:
            name = t.get("name", "")
            unit = registered.get(name)
            status = "registered" if unit else (t.get("status", "pending"))
            cat = t.get("category", "未归类")

            occ_baseline = self._occupation_baseline(t.get("id", ""))
            source = self._baseline_source(t.get("id", ""), bool(unit))
            if source == "stale":
                problems.append(
                    f"分区 {t.get('id')} 在职业库有职业登记但无一标记 "
                    f"baseline_occupation，岗位基线已静默回落兜底")
            if unit:  # 已注册单元覆盖该目标行业
                covered_industry += 1
                covered_roles = len(unit.roles)
                # 已注册行业：职业库基线优先，缺失时以实际注册岗位为准
                role_baseline = occ_baseline if occ_baseline is not None \
                    else len(unit.roles)
            else:
                covered_roles = 0
                # 待覆盖行业：职业库基线优先，缺失时按 target_roles 声明计
                role_baseline = occ_baseline if occ_baseline is not None \
                    else len(t.get("target_roles", []) or [])

            covered_role_total += covered_roles
            role_baseline_total += role_baseline

            # 按大类聚合
            bc = by_category.setdefault(cat, {"total": 0, "covered": 0})
            bc["total"] += 1
            if unit:
                bc["covered"] += 1

            rows.append({
                "id": t.get("id", ""),
                "name": name,
                "category": cat,
                "status": status,
                "unit_id": unit.unit_id if unit else "",
                "priority": t.get("priority", ""),
                "roles": {
                    "covered": covered_roles,
                    "baseline": role_baseline,
                    "baseline_source": source,
                    "names": [r.name for r in unit.roles] if unit else t.get("target_roles", []),
                },
                "channels": t.get("channels", []),
                "note": t.get("note", ""),
            })

        covered_industry_out = covered_industry
        pending = total - covered_industry_out
        return {
            "version": self.version,
            "updated_at": self.updated_at,
            "total_industries": total,
            "covered_industries": covered_industry_out,
            "pending_industries": pending,
            "industry_coverage": (covered_industry_out / total) if total else 0.0,
            "total_role_baseline": role_baseline_total,
            "covered_roles": covered_role_total,
            "role_coverage": (covered_role_total / role_baseline_total)
                             if role_baseline_total else 0.0,
            "by_category": by_category,
            "problems": problems,
            "rows": rows,
        }

    # ------------------------------------------------------------ render
    def render_text(self) -> str:
        """渲染为人类可读的覆盖进度表(供 CLI coverage 命令打印)。"""
        s = self.compute()
        lines = []
        lines.append("=" * 60)
        lines.append(f"行业岗位覆盖进度  coverage-target v{s['version']}"
                     f"  updated {s['updated_at']}")
        lines.append("-" * 60)
        lines.append(
            f"行业覆盖: {s['covered_industries']}/{s['total_industries']}  "
            f"({s['industry_coverage']:.1%})   待覆盖: {s['pending_industries']}")
        lines.append(
            f"岗位覆盖: {s['covered_roles']}/{s['total_role_baseline']}  "
            f"({s['role_coverage']:.1%})")
        lines.append("-" * 60)
        lines.append(f"{'状态':<4}{'目标行业':<12}{'覆盖岗位/基线':<16}类别")
        for r in sorted(s["rows"], key=lambda x: (x["status"] != "registered",
                                                  x["name"])):
            mark = "已覆盖" if r["status"] == "registered" else "待补"
            rc = r["roles"]["covered"]
            rb = r["roles"]["baseline"]
            role_txt = f"{rc}/{rb}"
            lines.append(
                f"{mark:<5}{r['name']:<12}{role_txt:<18}{r['category']}")
        lines.append("=" * 60)
        return "\n".join(lines)

    def gaps(self) -> List[dict]:
        """返回待覆盖缺口(用于辅助多渠道搜集与排期)。"""
        return [r for r in self.compute()["rows"] if r["status"] != "registered"]
