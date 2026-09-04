"""M1 行业识别·意图路由 + M4 会话编排判定"""
from __future__ import annotations

from typing import Dict, List, Optional

from .models import IndustryUnit, RouteResult, Role
from .registry import Registry


class IntentRouter:
    """
    M1 自动识别路由：
    将用户意图文本识别为 (行业单元, 岗位列表)，支持多岗位复合意图。
    """

    # 全局岗位关键词词典（中文动词/领域词 → 岗位）
    # 岗位词是跨单元通用的能力信号。
    ROLE_KEYWORDS: Dict[str, List[str]] = {
        "architect": ["架构设计", "架构方案", "架构师", "做架构", "总体设计", "技术方案",
                      "系统设计", "方案设计", "架构"],
        "developer": ["开发", "编码", "实现", "写代码", "落地", "编程", "实现代码", "写程序"],
        "reviewer":  ["评审", "审查", "复核", "走查", "检视", "代码审查"],
        "product":   ["产品", "需求", "规划", "排期", "产品方案", "竞品分析", "需求分析"],
        "secretary": ["编排", "记录", "秘书", "汇总", "会议纪要", "组织协调"],
        "game_planner": ["玩法", "数值策划", "策划", "游戏设计", "关卡"],
        "level_designer": ["关卡设计", "地图设计", "场景布置"],
    }

    # 岗位优先级（用于复合仲裁的依赖序）
    ROLE_PRIORITY: List[str] = [
        "secretary", "product", "architect", "developer", "reviewer",
        "game_planner", "level_designer",
    ]

    def __init__(self, registry: Optional[Registry] = None):
        self.registry = registry or Registry()

    def route(self, text: str) -> RouteResult:
        """对用户意图做多级路由判定"""
        if not text or not text.strip():
            return RouteResult(
                unit_id="", industry="", roles=[],
                confidence=0.0, needs_manual=True,
                fallback_reason="空输入"
            )

        # 第一步：识别岗位关键词（先全局收集）
        global_role_hits = self._collect_global_role_hits(text)

        # 第二级：行业识别 → 确定单元
        unit = self._identify_industry(text, global_role_hits)

        if unit is None:
            return RouteResult(
                unit_id="", industry="", roles=[],
                confidence=0.0, needs_manual=True,
                fallback_reason="未命中任何行业单元"
            )

        # 在确定单元内识别岗位
        matched_roles = self._identify_roles(text, unit)

        if not matched_roles:
            # 行业命中但岗位未命中 → 路由到单元默认入口
            return RouteResult(
                unit_id=unit.unit_id, industry=unit.industry,
                roles=[], confidence=0.4,
                matched_keywords={}, needs_manual=False,
                fallback_reason="仅行业命中"
            )

        confidence = self._calc_confidence(text, unit, matched_roles)

        return RouteResult(
            unit_id=unit.unit_id,
            industry=unit.industry,
            roles=[r.name for r in matched_roles],
            confidence=confidence,
            matched_keywords={r.name: self._match_kw(text, r) for r in matched_roles},
            needs_manual=confidence < 0.35,
        )

    def _collect_global_role_hits(self, text: str) -> Dict[str, List[str]]:
        """全局扫描：在文本中找出命中的岗位关键词（不依赖单元上下文）"""
        hits = {}
        for role_name, keywords in self.ROLE_KEYWORDS.items():
            matched = [kw for kw in keywords if kw and kw in text]
            if matched:
                hits[role_name] = matched
        return hits

    def _identify_industry(self, text: str, role_hits: Dict = None) -> Optional[IndustryUnit]:
        """识别文本对应的行业单元"""
        role_hits = role_hits or {}
        units = self.registry.all_units()
        if not units:
            return None

        # 收集每单元的 role 名称到名称映射
        unit_role_map = {}
        for unit in units:
            unit_role_map[unit.unit_id] = {r.name for r in unit.roles}

        best_unit = None
        best_score = 0.0

        for unit in units:
            score = 0.0

            # 1. 行业别名直接命中（强信号）
            for alias in unit.industry_alias:
                if alias and alias in text:
                    score += 2.0

            # 2. capability_tags 命中（中信号）
            for tag in unit.capability_tags:
                if tag and tag in text:
                    score += 1.5

            # 3. 全局岗位词命中且该岗位属于此单元（弱信号）
            unit_roles = unit_role_map.get(unit.unit_id, set())
            for role_name in role_hits:
                if role_name in unit_roles:
                    score += 0.5

            if score > best_score:
                best_score = score
                best_unit = unit

        # 只要有任意命中（哪怕只是全局岗位词与单元角色匹配），返回 best_unit
        if best_score > 0 and best_unit:
            return best_unit
        return None

    def _identify_roles(self, text: str, unit: IndustryUnit) -> List[Role]:
        """识别文本对应单元内的哪些岗位被命中（可能多个=复合）"""
        hits: List[Role] = []

        for r in unit.roles:
            # 该角色在全局词典中的关键词
            keywords = list(self.ROLE_KEYWORDS.get(r.name, []))
            # 角色描述也包含关键词
            if r.description:
                keywords.extend(r.description.split())
            if self._match_any(text, keywords):
                hits.append(r)

        hits.sort(key=lambda r: self.ROLE_PRIORITY.index(r.name)
                  if r.name in self.ROLE_PRIORITY else 99)
        return hits

    def _match_any(self, text: str, keywords: List[str]) -> bool:
        for kw in keywords:
            if kw and kw in text:
                return True
        return False

    def _match_kw(self, text: str, role: Role) -> List[str]:
        """返回文本中命中该角色的关键词"""
        keywords = list(self.ROLE_KEYWORDS.get(role.name, []))
        if role.description:
            keywords.extend(role.description.split())
        return [kw for kw in keywords if kw and kw in text]

    def _calc_confidence(self, text: str, unit: IndustryUnit, roles: List[Role]) -> float:
        """置信度计算：行业命中 + 岗位命中共同决定"""
        base = 0.0

        # 行业层面信号
        for alias in unit.industry_alias:
            if alias and alias in text:
                base += 0.3
        for tag in unit.capability_tags:
            if tag and tag in text:
                base += 0.2

        # 岗位层面信号
        for r in roles:
            kws = self._match_kw(text, r)
            if kws:
                base += 0.2 * min(len(kws), 3)

        return round(min(base, 1.0), 2)


class CompositePlanner:
    """
    M4 会话编排判定 + M6 复合agent装配器
    """

    def __init__(self, registry: Optional[Registry] = None):
        self.registry = registry or Registry()

    def plan(self, text: str) -> dict:
        """根据路由结果决定会话编排方案"""
        router = IntentRouter(self.registry)
        result = router.route(text)

        if result.needs_manual:
            return {
                "mode": "manual",
                "reason": result.fallback_reason,
                "message": f"置信度不足，回落 L2 人工确认。意图: {text}",
            }

        unit = self.registry.get_unit(result.unit_id)
        if not unit:
            return {"mode": "error", "message": f"单元不存在: {result.unit_id}"}

        hit_roles = [unit.role_by_name(r) for r in result.roles if unit.role_by_name(r)]

        if not hit_roles:
            # 仅行业命中
            return {
                "mode": "unit_default",
                "unit_id": unit.unit_id,
                "industry": unit.industry,
                "message": f"仅命中行业 {unit.industry}，路由到 {unit.unit_id} 默认入口",
            }

        if len(hit_roles) == 1:
            # 单直连
            role = hit_roles[0]
            return {
                "mode": "direct",
                "unit_id": unit.unit_id,
                "industry": unit.industry,
                "role": role.name,
                "role_prefix": role.prefix,
                "session_prefix": role.prefix,
                "message": f"单直连 → {unit.unit_id}@{role.name}",
            }

        # 多岗位 → 复合装配判定
        all_comp = all(r.composite for r in hit_roles)
        if all_comp:
            prefixes = [r.prefix for r in hit_roles]
            order = [r.name for r in hit_roles]
            return {
                "mode": "composite",
                "unit_id": unit.unit_id,
                "industry": unit.industry,
                "roles": order,
                "session_prefix_set": prefixes,
                "message": f"复合装配: {unit.unit_id} 同session并装岗位 {order}",
                "execution_order": order,
            }
        else:
            # 含不可复合岗位 → 需拆 session 走交接
            return {
                "mode": "handoff_required",
                "unit_id": unit.unit_id,
                "industry": unit.industry,
                "roles": [r.name for r in hit_roles],
                "message": "命中岗位含不可复合项，需拆新session经 M5 交接卡接力",
                "handoff_required": True,
            }
