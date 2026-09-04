"""数据模型定义"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Role:
    """行业单元内的岗位定义"""
    name: str
    prefix: str
    handoff: str = "relay"      # relay | direct
    composite: bool = True
    description: str = ""


@dataclass
class IndustryUnit:
    """一个行业单元（如 dongjiagoushi = 软件研发·架构团队）"""
    unit_id: str
    industry: str
    industry_alias: List[str]
    roles: List[Role]
    entry_ref: str = ""
    capability_tags: List[str] = field(default_factory=list)
    register_version: str = "1.0"

    def role_by_name(self, name: str) -> Optional[Role]:
        for r in self.roles:
            if r.name == name:
                return r
        return None


@dataclass
class RouteResult:
    """路由判定结果"""
    unit_id: str
    industry: str
    roles: List[str]          # 命中的岗位列表（可能多个=复合）
    confidence: float         # 0-1
    matched_keywords: Dict[str, List[str]] = field(default_factory=dict)
    is_ambiguous: bool = False
    needs_manual: bool = False  # 需回落L2人工确认
    fallback_reason: str = ""


@dataclass
class CompositePlan:
    """M6 复合装配计划"""
    unit_id: str
    session_industry: str
    roles: List[Role]
    session_prefix_set: List[str]  # 稳定前缀集合
    execution_order: List[str]     # 岗位执行顺序（依赖序）


@dataclass
class HandoffCard:
    """M5 跨单元交接卡"""
    source_unit: str
    target_unit: str
    intent: str
    context: str = ""
    status: str = "created"  # created | in_progress | done | failed
    created_at: Optional[str] = None
    id: Optional[str] = None  # 运行时生成的唯一ID
