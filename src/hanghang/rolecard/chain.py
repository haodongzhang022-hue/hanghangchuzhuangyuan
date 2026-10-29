"""利益链条归一（M11.1）：链上只写「行业类」，具体公司靠索引去查，不落库。

问题：岗位画像要通用，链条上游不能写死成"某某钢材加工厂"。
      写死公司，换一家客户整张画像就废了，也没法跨行业复用。

落法（三层）：
  ① 画像里写 **industry_class**（类目）：钢材加工 / 品牌方 / 用人部门 …
     —— 稳定、可共享、跨行业可用
  ② 类目 → 具体公司，靠 **index**（检索方式）现查：企业名录 / CRM / ATS / 内部主数据
     —— 只存检索方案，不存公司名录
  ③ 词表 data/industry-classes.yaml 是唯一口径来源，也管别名收敛

本模块只做两件事：归一（resolve）+ 校验（validate）。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import yaml

CLASS_FILE = "industry-classes.yaml"

# 引用种类
KIND_CLASS = "industry_class"
KIND_INTERFACE = "interface"
KIND_ROLE = "role"
KIND_UNREGISTERED = "unregistered"

# 链上的字段（都按同一口径归一）
CHAIN_FIELDS = ("upstream", "downstream", "beneficiaries", "blockers")

# 词表里这些 kind 视作"接口/渠道"，不算行业类目
INTERFACE_KINDS = ("接口", "渠道")

# 这些 kind 天生不需要"公司索引"（不是公司/实体，只是输入或原因）
NO_INDEX_KINDS = ("接口", "渠道", "需求", "输入", "阻碍", "内部组织", "资源")


@dataclass
class ChainEntry:
    """归一后的一项引用。"""
    raw: str
    value: str
    kind: str
    ref: str = ""            # "industry_class:钢材加工"
    index: Optional[dict] = None
    unit: str = ""           # kind=role 且跨单元时填
    note: str = ""

    def as_dict(self) -> dict:
        out = {"raw": self.raw, "value": self.value, "kind": self.kind, "ref": self.ref}
        if self.index:
            out["index"] = self.index
        if self.unit:
            out["unit"] = self.unit
        if self.note:
            out["note"] = self.note
        return out


@dataclass
class Issue:
    """校验发现的问题：error 拦住，warn 放行但要看见。"""
    level: str
    unit_id: str
    role: str
    field: str
    value: str
    message: str

    def __str__(self) -> str:
        tag = "✗" if self.level == "error" else "!"
        return f"{tag} {self.unit_id}/{self.role}.{self.field} =「{self.value}」{self.message}"


class IndustryClassIndex:
    """行业类词表 + 归一器。"""

    def __init__(self, data_dir: str, unit_roles: Optional[Dict[str, List[str]]] = None):
        self.data_dir = data_dir
        self.path = os.path.join(data_dir, CLASS_FILE)
        raw = self._load(self.path)
        self.version = str(raw.get("version", "0"))
        self.company_markers: Tuple[str, ...] = tuple(
            str(x) for x in (raw.get("company_markers") or []) if str(x).strip()
        )
        self.classes: Dict[str, dict] = {
            str(k): dict(v or {}) for k, v in (raw.get("classes") or {}).items()
        }
        self.aliases: Dict[str, list] = dict(raw.get("aliases") or {})
        # 单元类目：中文行业名 → unit_id（如 内容创作 → content-creation）
        self.unit_alias: Dict[str, str] = {}
        for key, spec in self.classes.items():
            if isinstance(spec, dict) and str(spec.get("kind", "")) == "单元":
                label = str(spec.get("label") or "").strip()
                if label:
                    self.unit_alias[label] = key
        self._alias_map: Dict[str, str] = {}
        for key, names in self.aliases.items():
            if str(key) in self.unit_alias:      # 单元的中文名走 unit_alias，不参与类目别名
                continue
            self._alias_map[str(key)] = str(key)
            for n in (names if isinstance(names, list) else [names]):
                if str(n) in self.unit_alias:
                    continue
                self._alias_map[str(n)] = str(key)
        self.unit_roles: Dict[str, List[str]] = dict(unit_roles or {})

    @staticmethod
    def _load(path: str) -> dict:
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return yaml.safe_load(fh) or {}
        except Exception:
            return {}

    # ------------------------------------------------------------ 归一口径
    def canonical(self, name: str) -> str:
        """叫法收敛到统一名（有别名就取别名，没有就用原名）。"""
        n = (name or "").strip()
        if n in self.unit_alias:          # 中文行业名 → 单元 id
            return self.unit_alias[n]
        return self._alias_map.get(n, n)

    def is_company_like(self, name: str) -> bool:
        """看起来像具体公司（而不是行业类）。"""
        n = (name or "").strip()
        return bool(n) and any(m in n for m in self.company_markers)

    def has_class(self, name: str) -> bool:
        return self.canonical(name) in self.classes

    def class_index(self, name: str) -> Optional[dict]:
        return (self.classes.get(self.canonical(name)) or {}).get("index")

    # ------------------------------------------------------------ 归一
    def resolve(self, raw: str, unit_id: str = "") -> ChainEntry:
        """把链上一项解析成带 kind / ref / index 的结构。

        顺序：别名收敛 → 词表类目 → 本单元岗位 → 其他单元岗位 → 未登记。
        """
        name = self.canonical(raw)
        if name in self.classes:
            spec = self.classes[name] or {}
            kind_label = str(spec.get("kind", ""))
            kind = KIND_INTERFACE if kind_label in INTERFACE_KINDS else KIND_CLASS
            display = str(spec.get("label") or name) if kind_label == "单元" else name
            return ChainEntry(raw=raw, value=display, kind=kind,
                              ref=f"{KIND_CLASS}:{name}", index=spec.get("index"),
                              note=kind_label)
        if name in (self.unit_roles.get(unit_id) or []):
            return ChainEntry(raw=raw, value=name, kind=KIND_ROLE,
                              ref=f"{KIND_ROLE}:{unit_id}/{name}", unit=unit_id)
        for uid, roles in sorted(self.unit_roles.items()):
            if uid != unit_id and name in roles:
                return ChainEntry(raw=raw, value=name, kind=KIND_ROLE,
                                  ref=f"{KIND_ROLE}:{uid}/{name}", unit=uid)
        return ChainEntry(raw=raw, value=name, kind=KIND_UNREGISTERED,
                          note="未登记为行业类，也未对应任何单元岗位")

    def normalize_chain(self, chain_values: Dict[str, List[str]], unit_id: str) -> Dict[str, List[ChainEntry]]:
        out: Dict[str, List[ChainEntry]] = {}
        for f in CHAIN_FIELDS:
            out[f] = [self.resolve(v, unit_id) for v in (chain_values.get(f) or [])]
        return out

    # ------------------------------------------------------------ 校验
    def validate(self, unit_id: str, role: str, field_name: str, values: List[str]) -> List[Issue]:
        issues: List[Issue] = []
        for v in values or []:
            if self.is_company_like(v):
                issues.append(Issue("error", unit_id, role, field_name, v,
                                    "写成了具体公司形态；链条只写行业类目，公司靠索引现查"))
                continue
            entry = self.resolve(v, unit_id)
            if entry.kind == KIND_UNREGISTERED:
                issues.append(Issue("error", unit_id, role, field_name, v,
                                    "未登记为行业类（请先在 data/industry-classes.yaml 登记）"))
            elif entry.kind == KIND_ROLE and entry.unit and entry.unit != unit_id:
                issues.append(Issue("warn", unit_id, role, field_name, v,
                                    f"引用 {entry.unit} 的岗位（跨单元复用，确认是有意的）"))
            elif entry.kind == KIND_CLASS and entry.index is None \
                    and entry.note not in NO_INDEX_KINDS \
                    and entry.note != "单元":
                issues.append(Issue("warn", unit_id, role, field_name, v,
                                    "类目已登记但未接索引（index: null），暂无公司检索方式"))
        return issues

    # ------------------------------------------------------------ 类目索引视图
    def class_usage(self, profiles: Dict[str, Dict[str, Dict[str, list]]]) -> Dict[str, dict]:
        """类目 → 被谁引用。这就是「把这个类落到列表和索引」的那份列表。

        profiles: {unit_id: {role: {field: [raw values]}}}
        """
        usage: Dict[str, dict] = {}
        for uid in sorted(profiles):
            for role in sorted(profiles[uid]):
                for fname, values in profiles[uid][role].items():
                    for v in values:
                        key = self.canonical(v)
                        if key not in self.classes:
                            continue
                        spec = self.classes[key] or {}
                        item = usage.setdefault(key, {
                            "class": key,
                            "kind": spec.get("kind", ""),
                            "index": spec.get("index"),
                            "used_by": [],
                        })
                        item["used_by"].append({"unit": uid, "role": role, "field": fname})
        return dict(sorted(usage.items()))


def unit_roles_from_registry(registry) -> Dict[str, List[str]]:
    return {u.unit_id: [r.name for r in u.roles] for u in registry.all_units()}
