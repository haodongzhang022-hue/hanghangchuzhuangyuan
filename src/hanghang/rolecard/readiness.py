"""岗位可插件化就绪度评分（M11）

回答一个很实际的问题：这个岗位现在「能不能上手干活」？
很多行业当前用不上，但架构上要先立起来 —— 所以缺字段不报错，只如实扣分并登记缺口。

五因子（权重见 data/rolecard-schema.yaml 的 readiness.weights）：
  six_dims     六维评估覆盖度   —— 契约字段齐不齐
  capability   核心能力平均分   —— 会不会干（0-5 归一到 0-1）
  workflow     工作流可执行度   —— 有没有工序、每步有没有 playbook/验证
  plugin       插件就绪度       —— 有没有包成可挂载的包
  beneficiaries 利益链条清晰度  —— 上下游/受益/阻碍写没写清
"""
from __future__ import annotations

from typing import Dict, List, Optional

from .models import CAPABILITY_DIMS, RUNTIME_ENUM, SIX_DIMENSIONS, ReadinessReport, RoleCard

# 默认口径（schema 文件缺失时的兜底，保证引擎可独立工作）
DEFAULT_WEIGHTS: Dict[str, float] = {
    "six_dims": 0.35,
    "capability": 0.25,
    "workflow": 0.20,
    "plugin": 0.10,
    "beneficiaries": 0.10,
}

DEFAULT_BANDS = [
    (75, "A", "可直接跑通"),
    (55, "B", "可跑需人工兜底"),
    (35, "C", "仅能问答"),
    (0, "D", "只有骨架"),
]

# 六维各自的关键字段（用于判定"这一维写全了没有"）
DIMENSION_FIELDS: Dict[str, tuple] = {
    "analysis": ("mission", "deliverables", "inputs", "outputs"),
    "persona": ("seniority", "mindset", "tone", "constraints"),
    "plugin": ("bundle", "tools", "artifacts"),
    "workflow": ("default_flow", "templates"),
    "stakeholders": ("upstream", "downstream", "beneficiaries", "risk_notes"),
    "capability": ("core", "scoring"),
}


def _filled(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    return True


class ReadinessScorer:
    """按 schema 口径给岗位卡打分并登记缺口。"""

    def __init__(self, weights: Optional[Dict[str, float]] = None,
                 bands: Optional[List[tuple]] = None):
        self.weights = dict(weights or DEFAULT_WEIGHTS)
        self.bands = list(bands or DEFAULT_BANDS)

    # ------------------------------------------------------- 六维覆盖度
    def six_dim_score(self, card: RoleCard, gaps: List[str]) -> float:
        p = card.profile
        if p is None:
            gaps.append("缺岗位画像基线（analysis/persona/plugin/workflow/stakeholders/capability 全缺）")
            return 0.0
        total = 0
        hit = 0
        for dim in SIX_DIMENSIONS:
            fields = DIMENSION_FIELDS.get(dim, ())
            payload = p.dimension(dim)
            total += len(fields)
            for f in fields:
                val = None
                if isinstance(payload, dict):
                    # workflow 维度允许把 templates/default_flow 放在 profile.workflow
                    val = payload.get(f)
                else:  # stakeholders / capability 是对象
                    val = getattr(payload, f, None)
                if _filled(val):
                    hit += 1
                else:
                    gaps.append(f"{dim}.{f} 未填")
        return round(hit / total, 3) if total else 0.0

    # ------------------------------------------------------- 能力均分
    def capability_score(self, card: RoleCard, gaps: List[str]) -> float:
        cap = card.capability()
        if not cap.scoring:
            gaps.append("capability.scoring 未评分（domain/tooling/judging/execution/comms）")
            return 0.0
        missing = [d for d in CAPABILITY_DIMS if not isinstance(cap.scoring.get(d), (int, float))]
        if missing:
            gaps.append(f"capability.scoring 缺维度: {', '.join(missing)}")
        return round(min(cap.average_score() / 5.0, 1.0), 3)

    # ------------------------------------------------------- 工作流可执行度
    def workflow_score(self, card: RoleCard, gaps: List[str]) -> float:
        if not card.workflows:
            gaps.append("无工作流（workflows 为空，无法从诉求走到交付）")
            return 0.0
        wf = card.default_workflow() or {}
        steps = card.playbook(str(wf.get("id", "")))
        if not steps:
            gaps.append("default 工作流无 steps")
            return 0.0
        per = [s.completeness() for s in steps]
        score = sum(per) / len(per)
        for s, c in zip(steps, per):
            if c < 1.0:
                lack = []
                if not s.playbook:
                    lack.append("playbook")
                if not s.verify:
                    lack.append("verify")
                if not s.outputs:
                    lack.append("outputs")
                gaps.append(f"步骤 {s.id or s.name} 缺: {', '.join(lack)}")
        # runtime 是否覆盖可落地形态（agent 以外至少要能导出）
        runtimes = {s.runtime for s in steps}
        if not runtimes.intersection(set(RUNTIME_ENUM)):
            gaps.append(f"步骤 runtime 非法: {sorted(runtimes)}")
        return round(score, 3)

    # ------------------------------------------------------- 插件就绪度
    def plugin_score(self, card: RoleCard, gaps: List[str]) -> float:
        p = card.profile
        if p is None or not p.plugin:
            gaps.append("plugin 未落地（bundle/tools/artifacts）")
            return 0.0
        keys = ("bundle", "tools", "artifacts")
        hit = sum(1 for k in keys if _filled(p.plugin.get(k)))
        if not card.plugin_artifacts:
            gaps.append("plugin_artifacts 为空（无上游技能包/技能文件可挂载）")
        # artifacts 落地加分：有真实技能包文件才算真能装
        art_bonus = 1.0 if card.plugin_artifacts else 0.0
        return round((hit / len(keys)) * 0.7 + art_bonus * 0.3, 3)

    # ------------------------------------------------------- 利益链条清晰度
    def beneficiary_score(self, card: RoleCard, gaps: List[str]) -> float:
        ch = card.chain()
        parts = {
            "upstream": ch.upstream,
            "downstream": ch.downstream,
            "beneficiaries": ch.beneficiaries,
            "blockers": ch.blockers,
            "risk_notes": ch.risk_notes,
        }
        hit = 0
        for name, val in parts.items():
            if _filled(val):
                hit += 1
            else:
                gaps.append(f"stakeholders.{name} 未填")
        return round(hit / len(parts), 3)

    # ------------------------------------------------------- 主入口
    def score(self, card: RoleCard) -> ReadinessReport:
        gaps: List[str] = []
        factors = {
            "six_dims": self.six_dim_score(card, gaps),
            "capability": self.capability_score(card, gaps),
            "workflow": self.workflow_score(card, gaps),
            "plugin": self.plugin_score(card, gaps),
            "beneficiaries": self.beneficiary_score(card, gaps),
        }
        total = sum(factors[k] * w for k, w in self.weights.items())
        final = round(total * 100, 1)
        grade, label = "D", "只有骨架"
        for min_score, g, lb in self.bands:
            if final >= min_score:
                grade, label = g, lb
                break
        report = ReadinessReport(
            role_name=card.role, unit_id=card.unit_id,
            score=final, grade=grade, label=label,
            factors={k: round(v, 3) for k, v in factors.items()},
            gaps=gaps,
        )
        card.readiness = report
        return report
