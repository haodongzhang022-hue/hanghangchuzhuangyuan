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
        """从搜索路径加载所有 industry-register*.yaml / unit-index*.yaml"""
        files = []
        for sp in self.search_paths:
            for pattern in ["industry-register*.yaml", "unit-index*.yaml"]:
                files.extend(glob.glob(os.path.join(sp, pattern)))
                # 递归必须写在 pattern 循环**里面**：写在外面时只会用到循环
                # 结束后残留的最后一个模式（unit-index*），于是 data/industry-register/
                # 这类子目录下的单元注册被静默忽略 —— 文件建了、加载器看不见，
                # 而 `units` 照常报旧数量，看起来「切块没生效」而不是「根本没读」。
                files.extend(glob.glob(os.path.join(sp, "**", pattern),
                                       recursive=True))

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
            self._register_unit(unit, path)
            return

        # 格式2: unit-index.yaml（含 units 列表）
        if isinstance(data.get("units"), list):
            for item in data["units"]:
                if "unit_id" in item:
                    unit = self._parse_unit(item)
                    self._register_unit(unit, path)

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
            entry_ref=str(data.get("entry_ref", "") or data.get("repo_ref", "")),
            capability_tags=[str(t) for t in data.get("capability_tags", [])],
            register_version=str(data.get("register_version", "1.0")),
        )

    @staticmethod
    def _role_sig(role: Role) -> tuple:
        """生成一个岗位的规范化签名，用于重复定义一致性比对。
        覆盖 name/prefix/handoff/composite/description/keywords，
        避免仅比对岗位名而遗漏 keywords/description 的静默分叉。
        """
        return (
            role.name,
            role.prefix,
            role.handoff,
            role.composite,
            role.description,
            tuple(sorted(role.keywords)),
        )

    def _unit_equal(self, a: IndustryUnit, b: IndustryUnit) -> bool:
        """两个单元定义是否完全一致（industry/aliases/version/capability/roles）"""
        if (a.industry != b.industry
                or a.industry_alias != b.industry_alias
                or a.register_version != b.register_version
                or a.capability_tags != b.capability_tags
                or a.entry_ref != b.entry_ref):
            return False
        a_roles = {self._role_sig(r) for r in a.roles}
        b_roles = {self._role_sig(r) for r in b.roles}
        return a_roles == b_roles

    def _register_unit(self, unit: IndustryUnit, source_path: str):
        """注册单元；若重复定义且内容不一致则警告（防止静默分叉）"""
        existing = self.units.get(unit.unit_id)
        if existing is not None:
            # 内容完全一致则后加载覆盖是幂等操作，不告警；
            # 覆盖 industry/aliases/version/capability/roles(keywords/description) 全字段比对
            if not self._unit_equal(existing, unit):
                logging.warning(
                    f"单元 {unit.unit_id} 被多文件重复定义且内容不一致: "
                    f"{source_path} 覆盖先前定义（industry/aliases/version/capability/"
                    f"roles(keywords/description) 存在差异，请核对数据同步）"
                )
        self.units[unit.unit_id] = unit

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

    def search_capability(self, keyword: str,
                          mode: str = "any") -> List[dict]:
        """
        M8 跨行业能力索引增强检索：
        在"知道哪个单元有该能力"之上，进一步精确到 该单元内
        由哪个岗位/哪个能力标签承接，并给出可路由入口地址。

        mode:
          - any:        任一维度命中即返回（行业别名/能力标签/岗位关键词/能力描述）
          - industry:   仅按 行业别名 命中
          - capability: 仅按 capability_tags 命中
          - role:       仅按 岗位关键词/岗位描述 命中

        返回 list[dict]，每项：
          {
            unit_id, industry, entry_ref,
            hit_kinds,       # 命中的所有维度: subset of {industry, capability, role}
            hit_roles,       # 命中该关键词的岗位列表
            hit_tags,        # 命中的能力标签
            matched_terms,   # 实际命中的词（含行业别名 + 能力标签）
          }
        """
        if not keyword or not keyword.strip():
            return []
        kw = keyword.strip()
        results = []
        for unit in self.units.values():
            hit_kinds = []
            hit_roles = []
            hit_tags = []
            matched_terms = []

            if mode in ("any", "industry"):
                for alias in unit.industry_alias:
                    if alias and kw in alias:
                        if "industry" not in hit_kinds:
                            hit_kinds.append("industry")
                        matched_terms.append(alias)

            if mode in ("any", "capability"):
                for tag in unit.capability_tags:
                    if tag and kw in tag:
                        if "capability" not in hit_kinds:
                            hit_kinds.append("capability")
                        hit_tags.append(tag)
                        # 能力维度命中的标签一并写入实际命中词
                        matched_terms.append(tag)

            if mode in ("any", "role"):
                for role in unit.roles:
                    role_kws = [w for w in role.get_keywords()
                                if w and kw in w]
                    if role_kws:
                        if "role" not in hit_kinds:
                            hit_kinds.append("role")
                        hit_roles.append(role.name)
                        matched_terms.extend(role_kws)

            if not hit_kinds:
                continue
            results.append({
                "unit_id": unit.unit_id,
                "industry": unit.industry,
                "entry_ref": unit.entry_ref,
                "hit_kinds": hit_kinds,
                "hit_roles": sorted(set(hit_roles)),
                "hit_tags": sorted(set(hit_tags)),
                "matched_terms": sorted(set(matched_terms)),
            })
        return results

    @staticmethod
    def _capability_tag_hits_role(tag: str, role: Role) -> bool:
        """判断一个能力标签是否由某岗位承接。
        评审 warning③：除岗位关键词与标签互相包含外，还比对岗位 name / description，
        减少因关键词措辞不完全一致导致的能力标签无承接岗位（提高 tag→role 命中率）。
        """
        if not tag:
            return False
        # 1) 岗位关键词 与 标签 互相包含（原规则）
        for w in role.get_keywords():
            if w and (w in tag or tag in w):
                return True
        # 2) 岗位名与标签语义包含（如 tag="预测分析" ↔ role name="data_scientist"? 不直接，
        #    但 keyword 含预测模型；此处兜底岗位名本身是否含标签词根）
        # 3) 岗位 description 中任一能力词与标签互相包含
        for d in role.description.replace(",", " ").replace("，", " ").split():
            if d and (d in tag or tag in d):
                return True
        # 4) 角色名中文/拼音与标签词根匹配兜底
        if role.name and (role.name in tag or tag in role.name):
            return True
        return False

    def capability_index(self) -> List[dict]:
        """
        M8 能力索引全量导出：供上层做能力编排/可视化面板聚合。
        返回每个单元的可路由能力清单（能力标签 → 对应岗位）。
        """
        index = []
        for unit in self.units.values():
            # 能力标签 → 承接岗位 映射
            tag_to_roles = {}
            for tag in unit.capability_tags:
                roles = []
                for role in unit.roles:
                    if self._capability_tag_hits_role(tag, role):
                        roles.append(role.name)
                tag_to_roles[tag] = roles
            index.append({
                "unit_id": unit.unit_id,
                "industry": unit.industry,
                "entry_ref": unit.entry_ref,
                "capability_tags": unit.capability_tags,
                "tag_to_roles": tag_to_roles,
                "roles": [{"name": r.name, "prefix": r.prefix,
                           "composite": r.composite, "handoff": r.handoff}
                          for r in unit.roles],
            })
        return index

    def summary(self) -> str:
        lines = [f"注册单元数: {len(self.units)}"]
        for uid, u in self.units.items():
            lines.append(f"  - {uid} [{u.industry}] roles={[r.name for r in u.roles]} aliases={u.industry_alias}")
        return "\n".join(lines)
