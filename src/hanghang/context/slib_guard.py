"""SLIB 上下文装配守卫（Session-Level Industry Binding · Assembly Guard）

本 Issue #8 核心诉求：改良加载机制——一个会话只装配"被锁定行业"的上下文，
杜绝在装配/注入阶段把非绑定行业乃至全量行业上下文带进单次调用。

路由层 SLIB（src/hanghang/engine/session_binding.py）已实现
"会话开始→锁定行业→跨行业=开新会话"的路由约束；本模块把同一强约束
**下沉到上下文装配层**：任何装配动作，若声称在某个 session 内进行，
则 unit_id 必须等于该 session 已绑定的行业单元。

- 已绑定 X + 装配 unit_id == X  → 放行
- 已绑定 X + 装配 unit_id == Y(≠X)  → 拦截（抛 SLIBBoundMismatch）
- 未绑定 + 传入 unit_id → 可自动绑定（auto_bind），随后放行
- 无 session_id → 视为静态单发装配（保留向后兼容，不强约束）

通过"守卫 + 绑定感知装配"两个入口落地，供 Web/CLI/上层 Agent 调用。
"""
from __future__ import annotations

from typing import Optional


class SLIBBoundMismatch(Exception):
    """装配行业与会话绑定行业不一致时抛出的守卫异常"""

    def __init__(self, session_id: str, bound_unit: str,
                 bound_industry: str, attempt_unit: str):
        self.session_id = session_id
        self.bound_unit = bound_unit
        self.bound_industry = bound_industry
        self.attempt_unit = attempt_unit
        super().__init__(
            f"SLIB 装配守卫：会话 {session_id} 已绑定行业"
            f"「{bound_industry}」({bound_unit})，禁止装配非绑定行业"
            f"上下文 {attempt_unit}。跨行业请开新会话。"
        )


class SLIBAssemblyGuard:
    """基于 SessionBindingStore 的装配守卫。

    惰性加载 SessionBindingStore（避免 context↔engine 循环依赖）。
    """

    def __init__(self, binding_store=None):
        self._binding_store = binding_store

    @property
    def binding_store(self):
        if self._binding_store is None:
            from hanghang.engine.session_binding import SessionBindingStore
            self._binding_store = SessionBindingStore()
        return self._binding_store

    def resolve_unit(self, session_id: str, unit_id: str,
                     industry: str = "", role_name: str = "",
                     auto_bind: bool = True) -> str:
        """把"待装配的 unit_id"与会话绑定对齐，返回最终应装配的 unit_id。

        若 session 已绑定其他行业而调用方想装配别处 → 抛 SLIBBoundMismatch。
        若 session 未绑定 → 按 auto_bind 决定是否将传入 unit_id 写入绑定。

        Returns:
            装配应使用的 unit_id（可能因自动绑定而等于传入值）。
        """
        if not session_id:
            # 无会话上下文：单发静态装配，不强约束
            return unit_id

        binding = self.binding_store.get_binding(session_id)
        if binding is not None:
            # 已绑定行业
            if unit_id and unit_id != binding.unit_id:
                raise SLIBBoundMismatch(
                    session_id, binding.unit_id, binding.industry, unit_id)
            return binding.unit_id

        # 未绑定
        if not unit_id:
            # 无从绑定：无法在会话内装配任何行业上下文
            raise ValueError(
                f"SLIB 装配守卫：会话 {session_id} 尚未绑定行业，"
                f"且未提供 unit_id，无法确定装配哪个行业上下文。"
            )
        if auto_bind:
            try:
                self.binding_store.bind(session_id, unit_id, industry or unit_id,
                                        role_name)
            except ValueError as exc:
                # 两种可能：并发下他进程已绑定，或 session_id 非法
                binding = self.binding_store.get_binding(session_id)
                if binding is None:
                    # 无绑定存在 → 是非法 session_id 等真实错误，重新抛出
                    raise exc
                if binding.unit_id != unit_id:
                    raise SLIBBoundMismatch(
                        session_id, binding.unit_id, binding.industry, unit_id)
        return unit_id


__all__ = ["SLIBAssemblyGuard", "SLIBBoundMismatch"]
