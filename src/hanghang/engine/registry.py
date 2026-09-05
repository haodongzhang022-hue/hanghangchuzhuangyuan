"""M2 行业/岗位注册表 & M8 跨行业能力索引"""
from __future__ import annotations

import logging
import os
import glob
from typing import Dict, List, Optional

import yaml

from .models import IndustryUnit, Role


class Registry:
    """
    M2 注册表：
    加载 industry-register.yaml 文件，维护行业单元注册。
    单文件 = 一个行业单元。
    """

    def __init__(self, search_paths: Optional[List[str]] = None):
        self.search_paths = search_paths or [
            os.path.join(os.getcwd(), "data"),
            os.path.join(os.path.dirname(__file__), "../../data"),
        ]
        self.units: Dict[str, IndustryUnit] = {}
        self._load_all()

    def _load_all(self):
        """从搜索路径加载所有 industry-register*.yaml"""
        files = []
        for sp in self.search_paths:
            for pattern in ["industry-register*.yaml", "unit-index*.yaml"]:
                files.extend(glob.glob(os.path.join(sp, pattern)))
            files.extend(glob.glob(os.path.join(sp, "**", pattern), recursive=True))

        # 优先 industry-register.yaml（单元自身声明），再 unit-index.yaml（索引视图）
        seen = set()
        for f in sorted(files):
            self._load_file(f)
            seen.add(f)

    def _load_file(self, path: str):
        """解析一个 YAML 文件到单元注册"""
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
        except Exception as e:
            logging.warning(f"跳过文件 {path}: {e}")
            return
        if not data:
            return

        # 格式1: 单单元文件 (含 unit_id 顶层)
        if "unit_id" in data:
            unit = self._parse_unit(data)
            self.units[unit.unit_id] = unit
            return

        # 格式2: unit-index.yaml（含 units 列表）
        if isinstance(data.get("units"), list):
            for item in data["units"]:
                if "unit_id" in item:
                    unit = self._parse_unit(item)
                    self.units[unit.unit_id] = unit

    def _parse_unit(self, data: dict) -> IndustryUnit:
        """从 dict 解析一个 IndustryUnit"""
        roles = []
        for r in data.get("roles", []):
            if isinstance(r, dict):
                roles.append(Role(
                    name=r.get("name", ""),
                    prefix=r.get("prefix", ""),
                    handoff=r.get("handoff", "relay"),
                    composite=r.get("composite", True),
                    description=r.get("description", ""),
                ))
            elif isinstance(r, str):
                roles.append(Role(name=r, prefix=f"[{r}]"))
        return IndustryUnit(
            unit_id=str(data.get("unit_id", "")),
            industry=str(data.get("industry", "")),
            industry_alias=list(data.get("industry_alias", [])),
            roles=roles,
            entry_ref=str(data.get("entry_ref", "")),
            capability_tags=list(data.get("capability_tags", [])),
            register_version=str(data.get("register_version", "1.0")),
        )

    def get_unit(self, unit_id: str) -> Optional[IndustryUnit]:
        return self.units.get(unit_id)

    def all_units(self) -> List[IndustryUnit]:
        return list(self.units.values())

    def search_by_keyword(self, keyword: str) -> Optional[IndustryUnit]:
        """M8 跨行业能力索引检索"""
        for unit in self.units.values():
            if keyword in unit.industry_alias or keyword in unit.capability_tags:
                return unit
        return None

    def summary(self) -> str:
        lines = [f"注册单元数: {len(self.units)}"]
        for uid, u in self.units.items():
            lines.append(f"  - {uid} [{u.industry}] roles={[r.name for r in u.roles]} aliases={u.industry_alias}")
        return "\n".join(lines)
