"""M1 行业识别·意图路由 + M4 会话编排判定 + M6 复合装配"""
from __future__ import annotations

from typing import Dict, List, Optional

from .models import IndustryUnit, RouteResult, Role
from .registry import Registry


class IntentRouter:
    """
    M1 自动识别路由：
    将用户意图文本识别为 (行业单元, 岗位列表)，支持多岗位复合意图。

    数据驱动设计：岗位关键词不再依赖全局硬编码词典，而是从各单元注册声明中
    动态读取每个岗位的触发关键词（role.keywords / role.description）。
    """

    # 默认岗位优先级（用于复合仲裁的依赖序）
    # 各单元也可通过复合 boundary 覆盖此顺序。
    DEFAULT_ROLE_PRIORITY: List[str] = [
        "secretary", "product", "architect", "developer", "reviewer",
        "game_planner", "level_designer", "game_dev",
    ]

    # 歧义判定阈值：top2 达到 top1 此比例即判为歧义（相对分差）
    AMBIGUITY_RATIO_THRESHOLD = 0.65

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

        # 第一步：全局行业单元评分（数据驱动）
        units = self.registry.all_units()
        if not units:
            return RouteResult(
                unit_id="", industry="", roles=[],
                confidence=0.0, needs_manual=True,
                fallback_reason="注册表为空，无可用单元"
            )

        # 计算每个单元的信号评分
        unit_scores = self._score_units(text, units)

        # 找到最高分单元（确定性 tie-break：同分时按 unit_id 字典序取小，
        # 不依赖注册文件加载/遍历顺序，保证路由归属稳定可复现）
        ranked_units = sorted(
            unit_scores.items(),
            key=lambda kv: (-kv[1]["score"], kv[0]),
        )
        best_unit_id = ranked_units[0][0] if ranked_units else ""
        best_score = unit_scores.get(best_unit_id, {}).get("score", 0.0)

        # 最高分单元得分<=0（无任何信号命中），此时无明确行业归属 → 人工确认
        # 修复：不再做悬空 global_role_hits 扫描后跳过，而是直接判人工回落
        if not best_unit_id or best_score <= 0:
            return RouteResult(
                unit_id="", industry="", roles=[],
                confidence=0.0, needs_manual=True,
                fallback_reason="未命中任何行业单元"
            )

        # 检查歧义：多个单元得分接近时需人工确认。
        # 规则：真正"跨行业冲突"必须满足——双方各自持有独立行业信号。
        # 若候选2的所有命中词均已被候选1命中（如泛化词"开发"在多个单元
        # 注册中重复出现），则仅属共享泛化词造成的伪歧义，不应回落人工。
        sorted_scores = sorted(unit_scores.items(),
                               key=lambda kv: (-kv[1]["score"], kv[0]))
        if len(sorted_scores) >= 2:
            top1, top2 = sorted_scores[0], sorted_scores[1]
            top1_score = top1[1]["score"]
            top2_score = top2[1]["score"]
            if (top1_score > 0 and top2_score > 0
                    and top2_score / top1_score >= self.AMBIGUITY_RATIO_THRESHOLD):
                # 泛化共享词过滤：候选2若无独立命中词（其词集⊆候选1），
                # 说明二者仅因同一泛化词(如"开发")撞分 → 非真歧义
                top1_terms = set(top1[1].get("matched_terms", []))
                top2_terms = set(top2[1].get("matched_terms", []))
                if not (top2_terms - top1_terms):
                    pass  # 伪歧义：继续走正常路由，不做人工回落
                else:
                    unit_ids = [t[0] for t in sorted_scores[:2]]
                    return RouteResult(
                        unit_id="", industry="", roles=[],
                        confidence=0.2, is_ambiguous=True, needs_manual=True,
                        fallback_reason=f"行业归属存在歧义: {unit_ids}"
                    )

        unit = self.registry.get_unit(best_unit_id)
        if not unit:
            return RouteResult(
                unit_id="", industry="", roles=[],
                confidence=0.0, needs_manual=True,
                fallback_reason=f"单元不存在: {best_unit_id}"
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
            needs_manual=confidence < 0.4,
        )


    def cross_unit_candidates(self, text: str):
        """
        检测文本是否命中多个"具有独立信号"的行业单元（真跨行业诉求）。
        返回按得分降序的单元列表；若仅有伪歧义（共享泛化词）则返回空/单元素。
        """
        units = self.registry.all_units()
        if not units or not text or not text.strip():
            return []

        unit_scores = self._score_units(text, units)
        hits = [(uid, sc) for uid, sc in unit_scores.items() if sc["score"] > 0]
        hits.sort(key=lambda kv: kv[1]["score"], reverse=True)

        if len(hits) < 2:
            return [hits[0][0]] if hits else []

        top1_uid, top1_info = hits[0]
        top2_uid, top2_info = hits[1]

        # 与歧义判定一致：若候选2的命中词 ⊆ 候选1，则属泛化伪歧义 → 非真跨行业
        top1_terms = set(top1_info.get("matched_terms", []))
        top2_terms = set(top2_info.get("matched_terms", []))
        if not (top2_terms - top1_terms):
            return [top1_uid]

        # 真跨行业：返回所有有正分的候选（≥2个），供 cross-unit 编排
        return [uid for uid, _ in hits]

    def _score_units(self, text: str, units: List[IndustryUnit]) -> Dict[str, dict]:
        """
        数据驱动：对每个单元做多维信号评分。
        信号来源：industry_alias + capability_tags + role keywords。
        """
        scores = {}
        for unit in units:
            score = 0.0
            matched_signals = []
            matched_terms: List[str] = []  # 实际命中的词（用于歧义时区分泛化共享）

            # 1. 行业别名直接命中（强信号，2.0）
            for alias in unit.industry_alias:
                if alias and alias in text:
                    score += 2.0
                    matched_signals.append(f"alias:{alias}")
                    matched_terms.append(alias)

            # 2. capability_tags 命中（中信号，1.0）
            for tag in unit.capability_tags:
                if tag and tag in text:
                    score += 1.0
                    matched_signals.append(f"tag:{tag}")
                    matched_terms.append(tag)

            # 3. 单元内岗位关键词命中（强信号，1.5/岗位）
            for role in unit.roles:
                for kw in role.get_keywords():
                    if kw and kw in text:
                        score += 1.5
                        matched_signals.append(f"role:{role.name}:{kw}")
                        matched_terms.append(kw)
                        break  # 每岗位只计一次

            scores[unit.unit_id] = {
                "score": round(score, 2),
                "signals": matched_signals,
                "matched_terms": matched_terms,
                "unit": unit,
            }
        return scores

    def _identify_roles(self, text: str, unit: IndustryUnit) -> List[Role]:
        """识别文本对应单元内的哪些岗位被命中（可能多个=复合）
        数据驱动：使用单元注册声明中的关键词而非全局词典。
        """
        hits: List[Role] = []

        for r in unit.roles:
            kws = r.get_keywords()
            if self._match_any(text, kws):
                hits.append(r)

        # 按默认优先级排序（稳定确定性输出）
        hits.sort(key=lambda r: self._role_priority_index(r.name))
        return hits

    def _role_priority_index(self, role_name: str) -> int:
        if role_name in self.DEFAULT_ROLE_PRIORITY:
            return self.DEFAULT_ROLE_PRIORITY.index(role_name)
        return len(self.DEFAULT_ROLE_PRIORITY)

    def _match_any(self, text: str, keywords: List[str]) -> bool:
        for kw in keywords:
            if kw and kw in text:
                return True
        return False

    def _match_kw(self, text: str, role: Role) -> List[str]:
        """返回文本中命中该角色的关键词"""
        return [kw for kw in role.get_keywords() if kw and kw in text]

    def _calc_confidence(self, text: str, unit: IndustryUnit,
                         roles: List[Role]) -> float:
        """置信度计算：行业命中 + 岗位命中共同决定
        关键规则：只要明确命中了行业单元且岗位，基础置信度 >= 0.5（可路由），
        通过多维信号叠加提高置信度。仅在行业/岗位信息模糊时才需人工。
        """
        base = 0.0

        # 岗位命中保证分：只要有岗位命中即+0.3
        if roles:
            base += 0.3

        # 行业层面信号（叠加）
        for alias in unit.industry_alias:
            if alias and alias in text:
                base += 0.25
        for tag in unit.capability_tags:
            if tag and tag in text:
                base += 0.15

        # 岗位层面信号（每岗位可叠加）
        for r in roles:
            kws = self._match_kw(text, r)
            if kws:
                base += 0.1 * min(len(kws), 3)

        return round(min(base, 1.0), 2)


class CompositePlanner:
    """
    M4 会话编排判定 + M6 复合agent装配器

    包含评审补强① 的 role_priority + boundary 规则：
    - 同行业多岗位复合：按 role_priority 依赖序装配
    - role 间通过交接卡传递产物，不互相污染记忆
    """

    # 默认复合装配的 role 优先执行顺序
    # 架构定方案先行，开发在后，评审在最后（符合"架构→开发→评审"链路）
    COMPOSITE_ORDER: Dict[str, int] = {
        "secretary": 0,
        "product": 1,
        "architect": 2,
        "game_planner": 2,
        "level_designer": 3,
        "developer": 4,
        "game_dev": 4,
        "reviewer": 5,
    }

    def __init__(self, registry: Optional[Registry] = None,
                 handoff_bus=None):
        self.registry = registry or Registry()
        # 注入交接总线（用于 M5 跨单元交接自动建卡）
        self.handoff_bus = handoff_bus
        if self.handoff_bus is None:
            try:
                from .handoff import HandoffBus
                self.handoff_bus = HandoffBus()
            except Exception:
                self.handoff_bus = None

    def plan(self, text: str) -> dict:
        """根据路由结果决定会话编排方案（内部路由一次后交 plan_from_result）"""
        router = IntentRouter(self.registry)
        result = router.route(text)
        return self.plan_from_result(result, text)

    def plan_from_result(self, result: "RouteResult", text: str) -> dict:
        """由已算好的路由结果决定会话编排方案。

        与 plan() 的区别：本方法不再重复做意图路由，直接基于传入的
        RouteResult 编排，避免同一意图被 route 两次（消除重复识别）。
        """
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
            # 按 COMPOSITE_ORDER 依赖序排列（role_priority 规则）
            ordered = sorted(hit_roles, key=lambda r: self.COMPOSITE_ORDER.get(r.name, 99))
            ordered_names = [r.name for r in ordered]
            prefixes = [r.prefix for r in ordered]
            return {
                "mode": "composite",
                "unit_id": unit.unit_id,
                "industry": unit.industry,
                "roles": ordered_names,
                "session_prefix_set": prefixes,
                "message": f"复合装配: {unit.unit_id} 同session并装岗位 {ordered_names}",
                "execution_order": ordered_names,
                # boundary 规则：岗位间仅经交接卡传递产物，不互相污染记忆
                "boundary": {
                    "role_isolation": "handoff_card_only",
                    "execution_order": ordered_names,
                    "rule": "architecture_before_dev_before_review",
                },
            }
        else:
            # 含不可复合岗位 → 需拆 session 走交接
            # M5：自动创建交接卡（而非仅提示）
            msg = "命中岗位含不可复合项，需拆新session经 M5 交接卡接力"
            card = None
            if self.handoff_bus:
                try:
                    card = self.handoff_bus.create_handoff(
                        source_unit=unit.unit_id,
                        target_unit=unit.unit_id,
                        intent=text,
                        context=f"角色 {[r.name for r in hit_roles]} 含不可复合岗位，需要交接接力",
                    )
                    msg += f" [交接卡已自动创建: {card.id}]"
                except Exception:
                    pass
            return {
                "mode": "handoff_required",
                "unit_id": unit.unit_id,
                "industry": unit.industry,
                "roles": [r.name for r in hit_roles],
                "message": msg,
                "handoff_required": True,
                "handoff_card_id": card.id if card else None,
            }

    def plan_cross_unit(self, text: str,
                        source_unit_id: str, target_unit_id: str) -> dict:
        """
        M5 跨单元交接编排：
        当一个意图命中了两个不同行业的单元时，
        自动创建交接卡，将任务拆分到各自的新 session 处理。
        """
        source = self.registry.get_unit(source_unit_id)
        target = self.registry.get_unit(target_unit_id)
        if not source or not target:
            return {"mode": "error", "message": "交接目标单元不存在"}

        card = None
        if self.handoff_bus:
            card = self.handoff_bus.create_handoff(
                source_unit=source_unit_id,
                target_unit=target_unit_id,
                intent=text,
                context=(
                    f"跨行业复合诉求，拆分到 {source.industry} 和 "
                    f"{target.industry} 各自的新 session 执行"
                ),
            )

        return {
            "mode": "cross_unit_handoff",
            "source_unit": source_unit_id,
            "target_unit": target_unit_id,
            "message": (
                f"跨行业复合: {source.unit_id}({source.industry}) → "
                f"{target.unit_id}({target.industry}) 需拆新session分别执行"
            ),
            "handoff_card_id": card.id if card else None,
        }
