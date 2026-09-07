"""M10 上下文装配器：防止提示词冗余 · 三层物理隔离 + 按规则注入"""
from .rules import ContextRule, RuleEngine, default_rules
from .assembler import ContextAssembler, default_assembler
from .cache_guard import CacheGuard
from .slib_guard import SLIBAssemblyGuard, SLIBBoundMismatch

__all__ = [
    "ContextRule", "RuleEngine", "default_rules",
    "ContextAssembler", "default_assembler",
    "CacheGuard",
    "SLIBAssemblyGuard", "SLIBBoundMismatch",
]
