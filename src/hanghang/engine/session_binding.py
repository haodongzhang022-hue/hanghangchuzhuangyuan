"""M4 SLIB 会话级行业绑定（Session-Level Industry Binding）

架构强约束（ARCHITECTURE.md §3.2）：
  **一个 session = 一个行业单元 = 一套稳定前缀。中途禁止跨行业。**

SLIB 提供会话级行业绑定的管理与执行：
  - SessionBindingStore：session→industry 绑定的持久化 + CRUD
  - SessionBoundRouter：会话感知的路由编排
      * 若 session 已绑定行业 X，后续消息在该会话内只能路由到 X 的岗位；
      * 若消息明显属于行业 Y（≠X），触发 cross_industry 信号（须开新 session 经交接）；
      * 若 session 未绑定，首次成功路由后自动绑定。

存储位置：data/bindings/<session_id>.json
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass, asdict
from typing import List, Optional

from .models import IndustryUnit, RouteResult
from .registry import Registry
from .prefix import PrefixArchive


# ---------------------------------------------------------------
# SessionBinding 数据模型
# ---------------------------------------------------------------

@dataclass
class SessionBinding:
    """会话级行业绑定记录"""
    session_id: str                # 会话 ID
    unit_id: str                   # 绑定的行业单元 ID
    industry: str                  # 行业标签（冗余，便于展示/检索）
    role_name: str = ""            # 绑定时命中的岗位（可选）
    bound_at: str = ""             # 绑定时间
    updated_at: str = ""           # 最近路由时间

    def __post_init__(self):
        if not self.bound_at:
            self.bound_at = time.strftime("%Y-%m-%d %H:%M:%S")
        if not self.updated_at:
            self.updated_at = self.bound_at

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SessionBinding":
        """从字典恢复，字段级容错"""
        if not isinstance(data, dict):
            return cls(session_id="", unit_id="", industry="")
        return cls(
            session_id=str(data.get("session_id", "")),
            unit_id=str(data.get("unit_id", "")),
            industry=str(data.get("industry", "")),
            role_name=str(data.get("role_name", "")),
            bound_at=str(data.get("bound_at", "")),
            updated_at=str(data.get("updated_at", "")),
        )


# ---------------------------------------------------------------
# SessionBindingStore：持久化管理
# ---------------------------------------------------------------

# session_id 白名单（与 StateManager 一致）
_SESSION_ID_PATTERN = re.compile(r'^[A-Za-z0-9_-]+$')


class SessionBindingStore:
    """
    会话级行业绑定的持久化存储：
    - 每个 session 一份 JSON 文件，存于 data/bindings/<session_id>.json
    - 提供 bind/unbind/get/list 操作
    - 线程安全（RLock：Web server 多线程复用单例）
    """

    def __init__(self, data_dir: Optional[str] = None):
        self.data_dir = data_dir or os.path.join(os.getcwd(), "data", "bindings")
        os.makedirs(self.data_dir, exist_ok=True)
        self._lock = threading.RLock()

    # ---- 校验 ----

    @staticmethod
    def _is_valid_session_id(session_id: str) -> bool:
        if not isinstance(session_id, str) or not session_id:
            return False
        return bool(_SESSION_ID_PATTERN.match(session_id))

    def _validate_session_id(self, session_id: str) -> None:
        if not self._is_valid_session_id(session_id):
            raise ValueError(
                f"非法 session_id: {session_id!r}。仅允许字母/数字/下划线/短横线 "
                f"([A-Za-z0-9_-])，防止路径穿越。"
            )

    def _binding_path(self, session_id: str) -> str:
        self._validate_session_id(session_id)
        return os.path.join(self.data_dir, f"{session_id}.json")

    # ---- CRUD ----

    def bind(self, session_id: str, unit_id: str, industry: str,
             role_name: str = "") -> SessionBinding:
        """将 session 绑定到指定行业单元。

        若 session 已绑定到其他行业，抛 ValueError（不覆盖已有绑定）。
        """
        self._validate_session_id(session_id)
        with self._lock:
            existing = self.get_binding(session_id)
            if existing is not None and existing.unit_id != unit_id:
                raise ValueError(
                    f"会话 {session_id} 已绑定到行业 {existing.industry}"
                    f"({existing.unit_id})，不能切换到 {industry}({unit_id})。"
                    f"如需跨行业请开新会话。"
                )
            binding = SessionBinding(
                session_id=session_id,
                unit_id=unit_id,
                industry=industry,
                role_name=role_name,
            )
            self._save(binding)
            return binding

    def update(self, session_id: str, role_name: str = "") -> bool:
        """更新会话绑定的最近路由岗位信息（不改变行业绑定）"""
        self._validate_session_id(session_id)
        with self._lock:
            binding = self.get_binding(session_id)
            if binding is None:
                return False
            if role_name:
                binding.role_name = role_name
            binding.updated_at = time.strftime("%Y-%m-%d %H:%M:%S")
            self._save(binding)
            return True

    def unbind(self, session_id: str) -> bool:
        """解除 session 的行业绑定（删除绑定文件）"""
        self._validate_session_id(session_id)
        with self._lock:
            path = self._binding_path(session_id)
            if os.path.exists(path):
                os.remove(path)
                return True
            return False

    def get_binding(self, session_id: str) -> Optional[SessionBinding]:
        """读取某 session 的行业绑定"""
        if not self._is_valid_session_id(session_id):
            return None
        with self._lock:
            path = self._binding_path(session_id)
            if not os.path.exists(path):
                return None
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return SessionBinding.from_dict(data)
            except Exception:
                return None

    def is_bound(self, session_id: str) -> bool:
        """判断 session 是否已绑定到某行业"""
        return self.get_binding(session_id) is not None

    def list_bindings(self) -> List[SessionBinding]:
        """列出所有已绑定的会话"""
        bindings = []
        if not os.path.isdir(self.data_dir):
            return bindings
        with self._lock:
            for fname in os.listdir(self.data_dir):
                if fname.endswith(".json") and not fname.endswith(".tmp"):
                    path = os.path.join(self.data_dir, fname)
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        b = SessionBinding.from_dict(data)
                        if b.session_id:
                            bindings.append(b)
                    except Exception:
                        continue
        return bindings

    def summary(self) -> str:
        """展示所有绑定关系的摘要"""
        bindings = self.list_bindings()
        if not bindings:
            return "(暂无会话行业绑定)"
        lines = [f"共 {len(bindings)} 个绑定:"]
        for b in sorted(bindings, key=lambda x: x.session_id):
            lines.append(
                f"  {b.session_id} → {b.industry}"
                f"({b.unit_id})" + (f" @{b.role_name}" if b.role_name else "")
            )
        return "\n".join(lines)

    # ---- 内部 ----

    def _save(self, binding: SessionBinding) -> None:
        path = self._binding_path(binding.session_id)
        # 原子写：先写临时文件再 rename
        tmp_path = path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(binding.to_dict(), f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


# ---------------------------------------------------------------
# SLIB：会话感知路由
# ---------------------------------------------------------------

class SessionBoundRouter:
    """
    M4 SLIB 会话感知路由编排器：
    在既有路由引擎之上叠加会话级行业绑定约束。

    使用方式：
        router = SessionBoundRouter()
        # 或指定 registry / planner / state_manager
        router = SessionBoundRouter(registry=reg, planner=planner)

        # 无 session_id → 与旧行为一致（纯意图路由）
        result = router.route(text)

        # 有 session_id → 会话感知路由
        result = router.route(text, session_id="sess-1")
        # => 若 sess-1 已绑定行业 X，本消息只能在 X 内路由；
        #    若消息明显属于其他行业 Y，则标记 cross_industry_handoff
    """

    # 跨行业冲突时的置信度阈值：低于此值的跨行业弱信号不触发 handoff，
    # 而是回落本行业默认入口（避免弱信号误触发跨行业拆分）。
    CROSS_INDUSTRY_CONFIDENCE_THRESHOLD = 0.4

    def __init__(self,
                 registry: Optional[Registry] = None,
                 state_manager=None,
                 binding_store: Optional[SessionBindingStore] = None,
                 prefix_archive: Optional[PrefixArchive] = None,
                 rolecard_store=None):
        from .router import IntentRouter, CompositePlanner
        self.registry = registry or Registry()
        # M11 岗位画像层（可选）：透传给 M1 做岗位激活加权；None 时行为不变
        self.rolecard_store = rolecard_store
        self.binding_store = binding_store or SessionBindingStore()
        # 惰性导入 StateManager（避免循环依赖）
        self._state_manager = state_manager

        # 会话感知的路由需要两个引擎：意图识别 + 会话编排
        self._router = IntentRouter(self.registry, rolecard_store=self.rolecard_store)
        self._planner = CompositePlanner(self.registry)

    @property
    def state_manager(self):
        """获取 StateManager 实例（惰性加载）"""
        if self._state_manager is None:
            from ..state.manager import StateManager
            self._state_manager = StateManager()
        return self._state_manager

    # ---- 对外主入口 ----

    def route(self, text: str, session_id: str = None,
              objective: str = "", auto_bind: bool = True) -> dict:
        """
        会话感知路由编排。

        参数:
            text: 用户意图文本
            session_id: 可选会话 ID。提供时执行 SLIB 约束；不提供则纯意图路由。
            objective: 可选总体目标（用于 StateCard 关联）
            auto_bind: 默认 True。会话未绑定行业时，首次路由成功后自动绑定。
        返回:
            dict，含 mode / plan / route_result / binding 等字段。
            mode 可能为:
              - "direct" / "composite" / "unit_default" / "manual"
                   同原有编排模式
              - "cross_industry_handoff"：会话已绑定行业 X，
                   本消息路由到行业 Y（≠X），触发跨行业交接建议
        """
        if not session_id:
            # 无会话上下文：退化为纯意图路由（保持向后兼容）
            return self._route_standalone(text)

        # 有会话上下文：执行 SLIB 约束
        return self._route_with_session(text, session_id, objective, auto_bind)

    def bind_session(self, session_id: str, unit_id: str,
                     industry: str, role_name: str = "") -> SessionBinding:
        """显式绑定 session 到行业单元"""
        return self.binding_store.bind(session_id, unit_id, industry, role_name)

    def unbind_session(self, session_id: str) -> bool:
        """解除 session 的行业绑定"""
        return self.binding_store.unbind(session_id)

    def get_binding(self, session_id: str) -> Optional[SessionBinding]:
        """获取 session 的行业绑定"""
        return self.binding_store.get_binding(session_id)

    def list_bindings(self) -> List[SessionBinding]:
        """列出所有已绑定会话"""
        return self.binding_store.list_bindings()

    # ---- 内部实现 ----

    def _route_standalone(self, text: str) -> dict:
        """纯意图路由（无会话上下文），与 CompositePlanner.plan() 一致"""
        result = self._router.route(text)
        plan = self._planner.plan_from_result(result, text)
        unit_prefixes = self._get_unit_prefixes(result.unit_id)
        return {
            "mode": plan.get("mode", "manual"),
            "plan": plan,
            "route_result": {
                "unit_id": result.unit_id,
                "industry": result.industry,
                "roles": result.roles,
                "confidence": result.confidence,
                "needs_manual": result.needs_manual,
                "fallback_reason": result.fallback_reason,
            },
            "session_aware": False,
            "binding": None,
            "unit_prefixes": unit_prefixes,
        }

    def _route_with_session(self, text: str, session_id: str,
                            objective: str = "", auto_bind: bool = True) -> dict:
        """会话感知路由（带 SLIB 绑定约束）"""
        existing = self.binding_store.get_binding(session_id)

        # 先做纯意图路由（获取新消息的自然路由结果）
        result = self._router.route(text)

        # 若会话尚未绑定行业 → 首次路由成功后自动绑定
        if existing is None:
            if result.needs_manual or not result.unit_id:
                # 未绑定 + 无法自动路由 → 回落人工
                plan = self._planner.plan_from_result(result, text)
                return {
                    "mode": "manual",
                    "plan": plan,
                    "route_result": self._result_to_dict(result),
                    "session_aware": True,
                    "binding": None,
                    "message": f"会话 {session_id} 尚未绑定行业，且本次路由需人工确认",
                    "unit_prefixes": self._get_unit_prefixes(result.unit_id),
                }
            # 绑定 session 到路由成功的行业
            if auto_bind:
                try:
                    self.binding_store.bind(
                        session_id=session_id,
                        unit_id=result.unit_id,
                        industry=result.industry,
                        role_name=result.roles[0] if result.roles else "",
                    )
                except ValueError:
                    # 并发场景下其他进程可能已绑定，读取新绑定继续
                    existing = self.binding_store.get_binding(session_id)
                    if existing is None:
                        raise
            else:
                existing = None  # 本次不自动绑定

        # 重新读取绑定（可能刚被 bind 写入）
        bound = self.binding_store.get_binding(session_id)
        if bound is not None:
            return self._route_in_bound_session(text, session_id, bound,
                                                result, objective)
        else:
            # 未自动绑定 → 按纯意图路由返回
            plan = self._planner.plan_from_result(result, text)
            return {
                "mode": plan.get("mode", "manual"),
                "plan": plan,
                "route_result": self._result_to_dict(result),
                "session_aware": True,
                "binding": None,
                "unit_prefixes": self._get_unit_prefixes(result.unit_id),
            }

    def _route_in_bound_session(self, text: str, session_id: str,
                                bound: SessionBinding,
                                fresh_result: RouteResult,
                                objective: str = "") -> dict:
        """在已绑定行业的会话内执行路由。

        SLIB 核心逻辑：
        1. 若新消息路由到同一行业 → 正常编排；
        2. 若新消息路由到不同行业 → 触发 cross_industry_handoff；
        3. 若新消息未命中任何行业 → 尝试在绑定行业内识别岗位。
        """
        # 情况 1.5：歧义（可能跨行业但无法确定）
        # 若绑定会话的消息被路由器标记为歧义（如在 legal 和 software 之间摇摆），
        # 优先在绑定行业领域内尝试解释：若绑定行业的关键词能命中则按绑定行业路由，
        # 避免"跨行业歧义"导致原本属于本行业上下文的消息被人工拦截。
        if (fresh_result.needs_manual and fresh_result.is_ambiguous
                and bound.unit_id is not None):
            bound_unit = self.registry.get_unit(bound.unit_id)
            bound_roles = self._identify_roles_in_unit(text, bound_unit) \
                if bound_unit is not None else []
            if bound_roles:
                from .models import RouteResult
                fresh_result = RouteResult(
                    unit_id=bound.unit_id,
                    industry=bound.industry,
                    roles=bound_roles,
                    confidence=0.5,
                    matched_keywords={},
                    needs_manual=False,
                )
                return self._route_in_bound_session(
                    text, session_id, bound, fresh_result, objective)

        # 情况 2：跨行业冲突
        if (fresh_result.unit_id and fresh_result.unit_id != bound.unit_id
                and not fresh_result.needs_manual):
            # 需要检查跨行业信号强度：太弱的跨行业信号不触发 handoff
            confidence = fresh_result.confidence
            if confidence >= self.CROSS_INDUSTRY_CONFIDENCE_THRESHOLD:
                # 跨行业 → 需开新 session 经交接
                # 尝试创建交接卡（可选）
                handoff_card_id = self._try_create_handoff(
                    bound.unit_id, fresh_result.unit_id, text)
                return {
                    "mode": "cross_industry_handoff",
                    "session_id": session_id,
                    "bound_unit_id": bound.unit_id,
                    "bound_industry": bound.industry,
                    "target_unit_id": fresh_result.unit_id,
                    "target_industry": fresh_result.industry,
                    "roles": fresh_result.roles,
                    "route_result": self._result_to_dict(fresh_result),
                    "binding": bound.to_dict(),
                    "handoff_card_id": handoff_card_id,
                    "message": (
                        f"会话 {session_id} 已绑定行业「{bound.industry}」"
                        f"({bound.unit_id})，本消息「{text}」路由到"
                        f"「{fresh_result.industry}」({fresh_result.unit_id})。"
                        f"按 SLIB 强约束不能同会话跨行业，请开新 session "
                        f"经 M5 交接卡接力处理。"
                    ),
                    "unit_prefixes": self._get_unit_prefixes(bound.unit_id),
                }

        # 情况 3：新消息命中同一行业，或未明确命中任何行业
        #          → 在绑定行业内路由（尝试识别绑定行业内的岗位）
        if fresh_result.unit_id == bound.unit_id or not fresh_result.unit_id:
            # 尝试在绑定行业内识别岗位：如果全局路由未命中任何行业（或仅命中
            # 同行业），但文本可能包含绑定行业内的岗位关键词（如"前端"在
            # 软件研发单元中命中 developer），则在绑定行业内做岗位识别。
            bound_unit = self.registry.get_unit(bound.unit_id)

            # 若全局路由失败（无任何行业命中），尝试在绑定单元内路由
            if (not fresh_result.unit_id and bound_unit is not None):
                # 在绑定行业内寻找匹配的岗位
                bound_roles = self._identify_roles_in_unit(text, bound_unit)
                if bound_roles:
                    # 构造一个"在绑定行业内路由成功"的结果
                    from .models import RouteResult
                    fresh_result = RouteResult(
                        unit_id=bound.unit_id,
                        industry=bound.industry,
                        roles=bound_roles,
                        confidence=max(fresh_result.confidence, 0.5),
                        matched_keywords={},
                        needs_manual=False,
                    )

            # 同行业：正常编排（plan_from_result）
            plan = self._planner.plan_from_result(fresh_result, text)
            # 更新绑定的最近路由信息
            self.binding_store.update(session_id, role_name=plan.get("role", ""))
            # 确保会话 StateCard 关联到绑定行业（若 persist_state 允许）
            state_card_id = plan.get("state_card_id")
            return {
                "mode": plan.get("mode", "manual"),
                "plan": plan,
                "route_result": self._result_to_dict(fresh_result),
                "session_aware": True,
                "session_id": session_id,
                "binding": self.binding_store.get_binding(session_id).to_dict(),
                "state_card_id": state_card_id,
                "unit_prefixes": self._get_unit_prefixes(bound.unit_id),
            }

        # 兜底：走原编排
        plan = self._planner.plan_from_result(fresh_result, text)
        return {
            "mode": plan.get("mode", "manual"),
            "plan": plan,
            "route_result": self._result_to_dict(fresh_result),
            "session_aware": True,
            "binding": bound.to_dict(),
            "unit_prefixes": self._get_unit_prefixes(bound.unit_id),
        }

    # ---- 辅助方法 ----

    def _identify_roles_in_unit(self, text: str, unit: IndustryUnit) -> List[str]:
        """在指定行业单元内识别命中的岗位。

        检查优先级：
        1. 角色关键词（最精确）
        2. 行业别名（次精确，如"法律"）
        3. 能力标签（较泛化）
        岗位识别仅看角色关键词；若角色关键词未命中但行业信号命中，
        返回空列表由上层决定如何路由。
        """
        hits = []
        if unit is None:
            return hits
        for role in unit.roles:
            for kw in role.get_keywords():
                if kw and kw in text:
                    hits.append(role.name)
                    break
        # 按默认优先级排序，保证确定性
        priority = [
            "secretary", "product", "architect", "developer", "reviewer",
        ]
        hits.sort(key=lambda name: priority.index(name) if name in priority else 99)
        return hits

    def _result_to_dict(self, result: RouteResult) -> dict:
        return {
            "unit_id": result.unit_id,
            "industry": result.industry,
            "roles": result.roles,
            "confidence": result.confidence,
            "matched_keywords": result.matched_keywords,
            "is_ambiguous": result.is_ambiguous,
            "needs_manual": result.needs_manual,
            "fallback_reason": result.fallback_reason,
        }

    def _get_unit_prefixes(self, unit_id: str) -> List[str]:
        """获取某行业单元的稳定前缀列表（来自 M3）"""
        try:
            from .prefix import PrefixArchive
            pa = PrefixArchive()
            # 确保已注册
            for unit in self.registry.all_units():
                pa.register_unit(unit, persist=False)
            prefixes = pa.get_unit_prefixes(unit_id)
            return prefixes or []
        except Exception:
            return []

    def _try_create_handoff(self, source_unit: str, target_unit: str,
                            intent: str) -> Optional[str]:
        """尝试创建跨行业交接卡；失败不阻断主流程"""
        try:
            from .handoff import HandoffBus
            bus = HandoffBus()
            card = bus.create_handoff(
                source_unit=source_unit,
                target_unit=target_unit,
                intent=intent,
                context=f"SLIB 会话级行业绑定：跨行业交接请求。",
                auto_state_card=True,
            )
            return card.id
        except Exception:
            return None


__all__ = [
    "SessionBinding",
    "SessionBindingStore",
    "SessionBoundRouter",
]
