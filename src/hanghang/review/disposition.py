"""统一审查处置标签（Review Disposition）

参考自 dongjiagoushi / youxikaifaxilieagent 的处置标签机制。
任何审查/决策点恒输出一个规范标签，统一口径、缺一即评审未完成。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class Disposition(str, Enum):
    """统一处置标签全集"""
    MERGE = "merge"            # 适合合并
    PROCEED = "proceed"        # 适合推进
    FIX_BUG = "fix_bug"        # 适合改bug
    RESEARCH = "research"      # 适合调研
    HUMAN = "human"            # 适合移交人类判断
    CONSULT = "consult"        # 适合专家会诊
    VOTE = "vote"              # 适合投票


# 处置标签顺序（用于排序/展示）
DISPOSITION_ORDER = [
    Disposition.MERGE,
    Disposition.PROCEED,
    Disposition.FIX_BUG,
    Disposition.RESEARCH,
    Disposition.HUMAN,
    Disposition.CONSULT,
    Disposition.VOTE,
]

# 归一化映射：零散信号 → 规范标签
# （仅用于单一信号独立判定的展示/检索，判定逻辑见 SIGNAL_PRIORITY）
SEVERITY_MAP = {
    "hard": Disposition.FIX_BUG,
    "high_risk": Disposition.CONSULT,
    "dispute": Disposition.VOTE,
    "needs_human": Disposition.HUMAN,
    "requires_human": Disposition.HUMAN,
    "skill_gap": Disposition.RESEARCH,
    "stall": Disposition.RESEARCH,
    "defect": Disposition.FIX_BUG,
    "adopt": Disposition.MERGE,
    "merge": Disposition.MERGE,
    "escalate": Disposition.HUMAN,
    "reroute": Disposition.RESEARCH,
    "approved": Disposition.MERGE,
    "changes_requested": Disposition.FIX_BUG,
}

# 触发信号 → 处置标签，按「介入强度」从高到低排序。
# 匹配采用词边界（避免子串误命中），且重叠信号（如 merge+escalate）时
# 取更高介入强度者，避免歧义。
#   高介入：human / vote / research / consult / fix_bug
#   低介入：merge（放最后，只有纯通过信号才落 merge）
SIGNAL_PRIORITY = [
    (r"\b(?:needs_human|requires_human|escalate)\b", Disposition.HUMAN),
    (r"\bdispute\b", Disposition.VOTE),
    (r"\b(?:skill_gap|stall|reroute)\b", Disposition.RESEARCH),
    (r"\bhigh_risk\b", Disposition.CONSULT),
    (r"\b(?:changes_requested|defect|hard)\b", Disposition.FIX_BUG),
    (r"\b(?:adopt|merge|approved)\b", Disposition.MERGE),
]


@dataclass
class ReviewResult:
    """审查处置结果"""
    disposition: Disposition
    severity: str = "info"     # critical | warning | info
    reason: str = ""
    labels: List[str] = field(default_factory=list)


def dispose(severity: str = "", trigger: str = "", context: str = "") -> ReviewResult:
    """
    确定性分类器：给定严重级 + 触发信号 + 场景，必然返回一个规范标签。
    无输入时按默认严重级（info）落到 merge。
    """
    severity_lower = (severity or "").strip().lower()
    trigger_lower = (trigger or "").strip().lower()

    # 严重级别 → 映射
    if severity_lower == "critical" or severity_lower == "hard":
        result = ReviewResult(disposition=Disposition.FIX_BUG, severity="critical")
    elif severity_lower == "high_risk":
        result = ReviewResult(disposition=Disposition.CONSULT, severity="warning")
    elif severity_lower == "warning" or severity_lower == "yellow" or severity_lower == "medium":
        result = ReviewResult(disposition=Disposition.PROCEED, severity="warning")
    else:
        result = ReviewResult(disposition=Disposition.MERGE, severity="info")

    # 触发信号 → 归一化（词边界 + 介入强度优先级，重叠时取高者）
    if trigger_lower:
        for pattern, disp in SIGNAL_PRIORITY:
            if re.search(pattern, trigger_lower):
                result.disposition = disp
                break

    # 补充原因说明
    if result.disposition == Disposition.FIX_BUG:
        result.reason = f"发现需修复问题: {context or trigger}"
    elif result.disposition == Disposition.MERGE:
        result.reason = f"审查通过，适合合并: {context or trigger}"
    elif result.disposition == Disposition.PROCEED:
        result.reason = f"可以继续推进: {context or trigger}"
    elif result.disposition == Disposition.HUMAN:
        result.reason = f"需移交人类判断: {context or trigger}"
    elif result.disposition == Disposition.CONSULT:
        result.reason = f"需专家会诊: {context or trigger}"
    elif result.disposition == Disposition.RESEARCH:
        result.reason = f"需外部调研: {context or trigger}"
    elif result.disposition == Disposition.VOTE:
        result.reason = f"需共识表决: {context or trigger}"

    # 标签集（供展示/打标）
    result.labels = [result.disposition.value, result.severity]
    return result


def parse_disposition(value: str) -> Optional[Disposition]:
    """将字符串解析为 Disposition 枚举，非规范值返回 None"""
    try:
        return Disposition(value)
    except (ValueError, TypeError):
        return None
