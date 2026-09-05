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

    数据驱动设计：各单元的岗位关键词（keywords）由注册声明自身提供，
    路由引擎从本注册表动态读取，无需修改代码即可新增行业单元。
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

        seen = set()
        for f in sorted(files):
            if f in seen:
                continue
            seen.add(f)
            self._load_file(f)

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
                # 兼容 roles 为 dict 对象与 roles 为 name 字符串两种写法
                role_name = str(r.get("name", ""))
                if not role_name and isinstance(r.get("role"), str):
                    role_name = r["role"]
                # 解析 keywords：显式 keywords 列表 > 单字符串 keywords > description
                keywords = []
                kw_val = r.get("keywords", [])
                if isinstance(kw_val, list):
                    keywords = [str(k) for k in kw_val if k]
                elif isinstance(kw_val, str):
                    keywords = [w.strip() for w in kw_val.replace(",", " ")
                                .replace("，", " ").split() if w.strip()]

                # 兼容 roles 仅含 name 字符串列表的情况
                role = Role(
                    name=role_name,
                    prefix=str(r.get("prefix", f"[{role_name}]")),
                    handoff=str(r.get("handoff", "relay")),
                    composite=bool(r.get("composite", True)),
                    description=str(r.get("description", "")),
                    keywords=keywords,
                )
                roles.append(role)
            elif isinstance(r, str):
                roles.append(Role(
                    name=r,
                    prefix=f"[{r}]",
                    keywords=[r],
                ))
        return IndustryUnit(
            unit_id=str(data.get("unit_id", "")),
            industry=str(data.get("industry", "")),
            industry_alias=[str(a) for a in data.get("industry_alias", [])],
            roles=roles,
            entry_ref=str(data.get("entry_ref", "")),
            capability_tags=[str(t) for t in data.get("capability_tags", [])],
            register_version=str(data.get("register_version", "1.0")),
        )

    def get_unit(self, unit_id: str) -> Optional[IndustryUnit]:
        return self.units.get(unit_id)

    def all_units(self) -> List[IndustryUnit]:
        return list(self.units.values())

    def search_by_keyword(self, keyword: str) -> List[IndustryUnit]:
        """M8 跨行业能力索引检索：返回所有匹配关键词的单元列表"""
        matches = []
        for unit in self.units.values():
            if (keyword in unit.industry_alias or
                    keyword in unit.capability_tags or
                    any(keyword in r.get_keywords() for r in unit.roles)):
                matches.append(unit)
        return matches

    def summary(self) -> str:
        lines = [f"注册单元数: {len(self.units)}"]
        for uid, u in self.units.items():
            lines.append(f"  - {uid} [{u.industry}] roles={[r.name for r in u.roles]} aliases={u.industry_alias}")
        return "\n".join(lines)
