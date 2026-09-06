"""核心引擎：路由、注册表、交接、指标、前缀档案"""
from .models import IndustryUnit, Role, RouteResult, CompositePlan, HandoffCard
from .registry import Registry
from .router import IntentRouter, CompositePlanner
from .handoff import HandoffBus
from .metrics import MetricsCollector
from .prefix import PrefixArchive

# M9 状态管理层
from hanghang.state.models import (
    StateCard, TaskRecord, TaskState, TaskType, FoldState,
)
from hanghang.state.manager import StateManager
from hanghang.state.fold_engine import FoldEngine
from hanghang.state.hierarchy import HierarchySubmitter, SecretaryTree, SecretaryTreeNode

__all__ = [
    "IndustryUnit", "Role", "RouteResult", "CompositePlan", "HandoffCard",
    "Registry", "IntentRouter", "CompositePlanner", "HandoffBus",
    "MetricsCollector", "PrefixArchive",
    # M9
    "StateCard", "TaskRecord", "TaskState", "TaskType", "FoldState",
    "StateManager", "FoldEngine", "HierarchySubmitter",
    "SecretaryTree", "SecretaryTreeNode",
]
