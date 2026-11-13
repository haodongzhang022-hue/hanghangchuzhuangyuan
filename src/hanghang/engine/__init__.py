"""核心引擎：路由、注册表、交接、指标、前缀档案 + M9 状态管理 + M10 上下文装配 + SLIB"""
from .models import IndustryUnit, Role, RouteResult, CompositePlan, HandoffCard
from .registry import Registry
from .router import IntentRouter, CompositePlanner
from .handoff import HandoffBus
from .metrics import MetricsCollector
from .prefix import PrefixArchive
from .coverage import CoverageTracker

# SLIB 会话级行业绑定
from .session_binding import (
    SessionBinding, SessionBindingStore, SessionBoundRouter,
)

# M9 状态管理层
from hanghang.state.models import (
    StateCard, TaskRecord, TaskState, TaskType, FoldState,
)
from hanghang.state.manager import StateManager
from hanghang.state.fold_engine import FoldEngine
from hanghang.state.content_archive import ContentArchive
from hanghang.state.hierarchy import HierarchySubmitter, SecretaryTree, SecretaryTreeNode
from hanghang.state.ownership import OwnershipGuard, CardLease, StateConflict, OwnershipDenied
from hanghang.state.arbiter import (
    ConflictArbiter, ReviewTicket, StateDiff, FieldChange,
    diff_state, diffs_overlap,
)
from hanghang.state.persist import FlushQueue, DeferredWriter

# M11 岗位画像层
from hanghang.rolecard import (
    RoleCard, RoleProfile, WorkflowStep, StakeholderChain,
    CapabilityProfile, ReadinessReport, RoleCardStore,
    ReadinessScorer, WorkflowRenderer,
)

# M10 上下文装配器
from hanghang.context import (
    ContextRule, RuleEngine, ContextAssembler, CacheGuard,
)

__all__ = [
    "IndustryUnit", "Role", "RouteResult", "CompositePlan", "HandoffCard",
    "Registry", "IntentRouter", "CompositePlanner", "HandoffBus",
    "MetricsCollector", "PrefixArchive", "CoverageTracker",
    # SLIB
    "SessionBinding", "SessionBindingStore", "SessionBoundRouter",
    # M9
    "StateCard", "TaskRecord", "TaskState", "TaskType", "FoldState",
    "StateManager", "FoldEngine", "ContentArchive", "HierarchySubmitter",
    "SecretaryTree", "SecretaryTreeNode",
    "OwnershipGuard", "CardLease", "StateConflict", "OwnershipDenied",
    "ConflictArbiter", "ReviewTicket", "StateDiff", "FieldChange",
    "diff_state", "diffs_overlap",
    "FlushQueue", "DeferredWriter",
    # M10
    "ContextRule", "RuleEngine", "ContextAssembler", "CacheGuard",
    # M11
    "RoleCard", "RoleProfile", "WorkflowStep", "StakeholderChain",
    "CapabilityProfile", "ReadinessReport", "RoleCardStore",
    "ReadinessScorer", "WorkflowRenderer",
]
