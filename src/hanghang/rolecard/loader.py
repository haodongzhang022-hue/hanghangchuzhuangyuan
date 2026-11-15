"""岗位画像卡加载器（M11）

数据源（全部数据驱动，缺目录/缺文件都优雅降级，不抛异常）：
  data/role-profiles/<unit_id>.yaml  人工画像基线（六维评估）
  data/rolecards/<unit_id>.yaml      渲染产物（可选，存在则优先用，保证生成结果可复现）
  data/workflow-templates/*.yaml     工作流模板
  注册表（M2）                       岗位名/前缀/关键词/行业（画像卡的"事实来源"）

加载顺序即"事实优先级"：注册表定岗位清单 → 画像基线补六维 → 模板渲染工作流 → 算就绪度。
"""
from __future__ import annotations

import glob
import os
from typing import Dict, List, Optional

import yaml

from .chain import (
    CHAIN_FIELDS, IndustryClassIndex, Issue, unit_roles_from_registry,
)
from .models import (
    CapabilityProfile, RoleCard, RoleProfile, StakeholderChain,
)
from .readiness import ReadinessScorer
from .workflow import MIN_FLOW, WorkflowRenderer


def _find_data_dirs() -> List[str]:
    """按优先级给出候选 data 目录（cwd 优先，其次仓库相对位置）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    return [
        os.path.join(os.getcwd(), "data"),
        os.path.abspath(os.path.join(here, "../../../data")),
    ]


class RoleCardStore:
    """岗位画像卡仓库：加载 + 渲染 + 查询。"""

    def __init__(self, registry=None, data_dir: Optional[str] = None):
        self.data_dir = data_dir or self._pick_data_dir()
        self.profile_dir = os.path.join(self.data_dir, "role-profiles")
        self.card_dir = os.path.join(self.data_dir, "rolecards")
        self.template_dir = os.path.join(self.data_dir, "workflow-templates")
        self.schema_path = os.path.join(self.data_dir, "rolecard-schema.yaml")

        if registry is None:
            from ..engine.registry import Registry
            registry = Registry()
        self.registry = registry

        self.schema: dict = self._load_yaml(self.schema_path) or {}
        self.renderer = WorkflowRenderer(self._load_templates())
        self.scorer = ReadinessScorer(self._schema_weights(), self._schema_bands(),
                                      self._schema_dimension_fields())
        self.profiles: Dict[str, Dict[str, RoleProfile]] = self._load_profiles()
        self._partitions_cache = None
        # M11.1：行业类词表（链上只存类，公司靠索引现查）
        self.classes = IndustryClassIndex(
            self.data_dir, unit_roles_from_registry(self.registry))
        # 行业战略视图：岗位卡说"这个岗位怎么干"，它说"这个行业的钱在哪"。
        # 缺失即空表（不阻断渲染），但漏了整个岗位卡就只剩岗位视角。
        # 延迟导入：engine/__init__ 会反向导入本包，顶层 import 会成环。
        from ..engine.strategy_view import StrategyView
        # 必须把 partitions / registry 一起传进去：`_roles_of()` 靠它们判断
        # "这个岗位落点在本分区是否真实存在"。不传时它只能回落到
        # `planned_roles`（已建分区多为空），于是**每张岗位卡都把合法落点报成悬空**
        # ——`role_focus_valid` 恒空、`role_focus_dangling` 恒全量。
        # 现在 `to_context_block()` 还没消费这两个字段，所以没露到下游；
        # 但字段一旦被 UI / 导出读走就是错结论。
        self.strategy = StrategyView(
            self.data_dir,
            partitions=self._industry_partitions(),
            registry=registry)
        self._strategy_bound = True
        self._cards: Dict[str, RoleCard] = {}

    def _industry_partitions(self):
        """分区表：复用行业库那一份，不在这里另读第二份。

        两处各读一份时，注册表与分区表的 bind 时机迟早不同步 ——
        而"哪个分区有哪些岗位"正是战略落点校验的唯一依据。
        """
        if self._partitions_cache is not None:
            return self._partitions_cache
        try:
            from ..engine.industry_db import IndustryDatabase
            self._partitions_cache = IndustryDatabase(self.data_dir).partitions
        except Exception:
            # 行业库读不出来时不影响岗位卡渲染：战略视图降级为空表。
            # 这里不吞成"没有分区"就报错，是因为岗位卡是主路径，
            # 行业库是附加判断；主路径不该因附加项拿不到而挂掉。
            self._partitions_cache = []
        return self._partitions_cache

    # ---------------------------------------------------------- 基础加载
    @staticmethod
    def _pick_data_dir() -> str:
        for c in _find_data_dirs():
            if os.path.isdir(c):
                return c
        return _find_data_dirs()[0]

    @staticmethod
    def _load_yaml(path: str) -> Optional[dict]:
        if not path or not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return yaml.safe_load(fh) or {}
        except Exception:
            return None

    def _schema_weights(self) -> Dict[str, float]:
        raw = ((self.schema.get("readiness") or {}).get("weights") or {})
        return {str(k): float(v) for k, v in raw.items() if isinstance(v, (int, float))} or None

    def _schema_dimension_fields(self) -> Dict[str, List[str]]:
        """六维字段清单的唯一来源：schema 的 dimensions[*].fields。"""
        out: Dict[str, List[str]] = {}
        for dim, spec in ((self.schema.get("dimensions") or {}) or {}).items():
            if not isinstance(spec, dict):
                continue
            fields = spec.get("fields")
            if isinstance(fields, list) and fields:
                out[str(dim)] = [str(f) for f in fields]
        return out

    def _schema_bands(self):
        raw = ((self.schema.get("readiness") or {}).get("bands") or [])
        bands = []
        for b in raw:
            if isinstance(b, dict) and "min" in b:
                bands.append((float(b["min"]), str(b.get("grade", "D")),
                              str(b.get("label", ""))))
        return bands or None

    def _load_templates(self) -> Dict[str, dict]:
        templates = {"min-flow": MIN_FLOW}
        for path in sorted(glob.glob(os.path.join(self.template_dir, "*.yaml"))):
            data = self._load_yaml(path)
            if not isinstance(data, dict):
                continue
            tid = str(data.get("id") or os.path.splitext(os.path.basename(path))[0])
            templates[tid] = data
        return templates

    def _load_profiles(self) -> Dict[str, Dict[str, RoleProfile]]:
        out: Dict[str, Dict[str, RoleProfile]] = {}
        for path in sorted(glob.glob(os.path.join(self.profile_dir, "*.yaml"))):
            data = self._load_yaml(path)
            if not isinstance(data, dict):
                continue
            unit_id = str(data.get("unit_id") or
                          os.path.splitext(os.path.basename(path))[0])
            roles = {}
            for item in data.get("roles", []) or []:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("role") or item.get("name") or "")
                if not name:
                    continue
                roles[name] = self._parse_role_profile(name, item, path)
            if roles:
                out[unit_id] = roles
        return out

    @staticmethod
    def _parse_role_profile(name: str, item: dict, source: str) -> RoleProfile:
        cap_raw = item.get("capability") or {}
        capability = CapabilityProfile(
            core=[str(x) for x in cap_raw.get("core", []) or []],
            tools=[str(x) for x in cap_raw.get("tools", []) or []],
            knowledge=[str(x) for x in cap_raw.get("knowledge", []) or []],
            soft=[str(x) for x in cap_raw.get("soft", []) or []],
            scoring={str(k): float(v) for k, v in (cap_raw.get("scoring") or {}).items()
                     if isinstance(v, (int, float))},
        )
        st_raw = item.get("stakeholders") or {}
        stakeholders = StakeholderChain(
            upstream=[str(x) for x in st_raw.get("upstream", []) or []],
            downstream=[str(x) for x in st_raw.get("downstream", []) or []],
            beneficiaries=[str(x) for x in st_raw.get("beneficiaries", []) or []],
            blockers=[str(x) for x in st_raw.get("blockers", []) or []],
            incentives=[str(x) for x in st_raw.get("incentives", []) or []],
            risk_notes=[str(x) for x in st_raw.get("risk_notes", []) or []],
        )
        return RoleProfile(
            role=name,
            analysis=dict(item.get("analysis") or {}),
            persona=dict(item.get("persona") or {}),
            plugin=dict(item.get("plugin") or {}),
            workflow=dict(item.get("workflow") or {}),
            stakeholders=stakeholders,
            capability=capability,
            source=source,
        )

    # ---------------------------------------------------------- 渲染
    def build_card(self, unit_id: str, role_name: str) -> Optional[RoleCard]:
        """按 注册表 + 画像基线 + 模板 渲染一张岗位卡（含就绪度评分）。"""
        unit = self.registry.get_unit(unit_id)
        if not unit:
            return None
        role = unit.role_by_name(role_name)
        if not role:
            return None

        profile = (self.profiles.get(unit_id) or {}).get(role_name)
        plugin_artifacts = list((profile.plugin.get("artifacts") if profile else []) or [])
        # plugin_artifacts 允许为字符串列表，统一成 {name, kind, path} 结构
        normalized = []
        for art in plugin_artifacts:
            if isinstance(art, dict):
                normalized.append(dict(art))
            elif isinstance(art, str):
                normalized.append({"name": art, "kind": "skill"})

        wf_specs = [s for s in ((profile.workflow.get("templates") if profile else []) or [])
                    if isinstance(s, dict)]
        default_flow = str((profile.workflow.get("default_flow") if profile else "") or "")
        workflows = self.renderer.render_all(wf_specs, role.name, default_flow)

        card = RoleCard(
            unit_id=unit.unit_id,
            industry=unit.industry,
            role=role.name,
            prefix=role.prefix,
            description=role.description,
            keywords=list(role.get_keywords()),
            profile=profile,
            workflows=workflows,
            plugin_artifacts=normalized,
            activation={},
            sources=[profile.source] if profile and profile.source else [],
        )
        card.chain_refs = self._normalize_chain(card, unit.unit_id)
        # 行业战略视图：只取本岗位所在分区的判断（分区 id 与 unit_id 缺省同名）
        card.industry_view = self.strategy.row(self._partition_of(unit.unit_id))
        card.activation = self._derive_activation(card, unit)
        self.scorer.score(card)
        return card

    def _partition_of(self, unit_id: str) -> str:
        """单元 → 行业分区 id。缺省同名（M11 的一致性对齐键），找不到就原样给。

        不在这里做模糊匹配：单元名与分区名对不上时，宁可空着让人看见，
        也不要猜一个"差不多的分区"，那样战略判断会静默套到别的行业上。
        """
        return unit_id

    def _normalize_chain(self, card: RoleCard, unit_id: str) -> Dict[str, List[dict]]:
        """把利益链条归一：行业类目带 ref/index，岗位带 unit，公司不落库。"""
        if card.profile is None:
            return {}
        raw = {f: list(getattr(card.profile.stakeholders, f) or []) for f in CHAIN_FIELDS}
        return {f: [e.as_dict() for e in entries]
                for f, entries in self.classes.normalize_chain(raw, unit_id).items()}

    # ---------------------------------------------------------- M11.1 链条校验
    def chain_issues(self, unit_id: str = "", role_name: str = "") -> List[Issue]:
        """校验链上引用：公司名/未登记类目 → error，未接索引 → warn。

        这是「把类落到列表和索引」的守门人：链上写死公司，这里就拦住。
        """
        issues: List[Issue] = []
        for uid, roles in sorted(self.profiles.items()):
            if unit_id and uid != unit_id:
                continue
            for rname, profile in sorted(roles.items()):
                if role_name and rname != role_name:
                    continue
                for field in CHAIN_FIELDS:
                    issues.extend(self.classes.validate(
                        uid, rname, field, getattr(profile.stakeholders, field)))
        return issues

    def class_usage(self) -> Dict[str, dict]:
        """行业类 → 被哪些岗位引用（类目列表 + 索引方案的落地视图）。"""
        view: Dict[str, Dict[str, Dict[str, list]]] = {}
        for uid, roles in self.profiles.items():
            for rname, profile in roles.items():
                view.setdefault(uid, {})[rname] = {
                    f: list(getattr(profile.stakeholders, f) or []) for f in CHAIN_FIELDS
                }
        return self.classes.class_usage(view)

    def _derive_activation(self, card: RoleCard, unit) -> dict:
        """路由激活条件：能干什么活（workflows）+ 什么行业语境（alias）+ 触发词 + 权重。"""
        acts = [w.get("name", w.get("id", "")) for w in card.workflows if w.get("name") or w.get("id")]
        weights = {}
        if card.profile:
            weights = dict((card.profile.workflow.get("activation") or {}))
        return {
            "workflows": [a for a in acts if a],
            "industry_alias": list(unit.industry_alias),
            "triggers": list(card.keywords),
            "weight": float(weights.get("weight", 1.0) or 1.0),
        }

    # ---------------------------------------------------------- 查询
    def all_cards(self) -> List[RoleCard]:
        cards = []
        for unit in self.registry.all_units():
            for role in unit.roles:
                card = self.get(unit.unit_id, role.name)
                if card:
                    cards.append(card)
        return cards

    def get(self, unit_id: str, role_name: str, use_cache: bool = True) -> Optional[RoleCard]:
        key = f"{unit_id}::{role_name}"
        if use_cache and key in self._cards:
            return self._cards[key]
        card = self.build_card(unit_id, role_name)
        if card is not None:
            self._cards[key] = card
        return card

    def cards_for_unit(self, unit_id: str) -> List[RoleCard]:
        unit = self.registry.get_unit(unit_id)
        if not unit:
            return []
        return [c for c in (self.get(unit_id, r.name) for r in unit.roles) if c]

    def find_role(self, role_name: str) -> List[RoleCard]:
        """按岗位名全局找卡（跨行业重名岗位会返回多张）。"""
        out = []
        for unit in self.registry.all_units():
            if unit.role_by_name(role_name):
                card = self.get(unit.unit_id, role_name)
                if card:
                    out.append(card)
        return out

    # ---------------------------------------------------------- 汇总
    def coverage_summary(self, cards=None) -> dict:
        """画像覆盖进度：多少岗位有画像、评级分布、平均分。

        ``cards`` 传入时只统计这批卡（如 ``role list --unit`` 的过滤结果），
        否则统计全库 —— 汇总数字必须与眼前列出的行同口径。
        """
        cards = self.all_cards() if cards is None else list(cards)
        total = len(cards)
        profiled = [c for c in cards if c.profile is not None]
        grades: Dict[str, int] = {}
        scores = []
        for c in cards:
            g = c.readiness.grade if c.readiness else "D"
            grades[g] = grades.get(g, 0) + 1
            if c.readiness:
                scores.append(c.readiness.score)
        return {
            "total_roles": total,
            "profiled_roles": len(profiled),
            "profile_coverage": round(len(profiled) / total, 3) if total else 0.0,
            "average_score": round(sum(scores) / len(scores), 1) if scores else 0.0,
            "grades": dict(sorted(grades.items())),
        }
