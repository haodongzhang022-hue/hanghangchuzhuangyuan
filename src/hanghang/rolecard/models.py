"""M11 数据模型：岗位画像卡 / 六维评估 / 工作流模板 / 就绪度报告"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# 六维评估维度（与 data/rolecard-schema.yaml 的 dimensions 对应）
SIX_DIMENSIONS: tuple = (
    "analysis", "persona", "plugin", "workflow", "stakeholders", "capability",
)

# 能力评分维度（capability.scoring）
CAPABILITY_DIMS: tuple = ("domain", "tooling", "judging", "execution", "comms")

RUNTIME_ENUM: tuple = ("agent", "n8n", "code")


@dataclass
class WorkflowStep:
    """工作流的一步工序：谁干、按什么 playbook 干、干完怎么验、用什么 runtime 落"""
    id: str
    name: str = ""
    agent_role: str = ""
    playbook: str = ""
    preconditions: List[str] = field(default_factory=list)
    outputs: List[str] = field(default_factory=list)
    verify: List[str] = field(default_factory=list)
    runtime: str = "agent"

    def executable(self) -> bool:
        """该步是否「可执行」：有 playbook/name 且 runtime 合法。"""
        return bool(self.playbook or self.name) and self.runtime in RUNTIME_ENUM

    def completeness(self) -> float:
        """步骤完整度 0-1：playbook / verify / outputs / runtime 各占一份。"""
        score = 0.0
        if self.playbook:
            score += 0.4
        if self.verify:
            score += 0.25
        if self.outputs:
            score += 0.2
        if self.runtime in RUNTIME_ENUM:
            score += 0.15
        return round(score, 2)


@dataclass
class StakeholderChain:
    """利益链条：谁给输入、谁接产物、谁受益、谁阻碍、凭什么不配合"""
    upstream: List[str] = field(default_factory=list)
    downstream: List[str] = field(default_factory=list)
    beneficiaries: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    incentives: List[str] = field(default_factory=list)
    risk_notes: List[str] = field(default_factory=list)


@dataclass
class CapabilityProfile:
    """核心能力：清单（做什么）+ 评分（做到什么程度）"""
    core: List[str] = field(default_factory=list)
    tools: List[str] = field(default_factory=list)
    knowledge: List[str] = field(default_factory=list)
    soft: List[str] = field(default_factory=list)
    scoring: Dict[str, float] = field(default_factory=dict)

    def average_score(self) -> float:
        """能力平均分（0-5）。未评分的维度不计入分母，避免虚高/虚低。"""
        vals = [float(self.scoring[d]) for d in CAPABILITY_DIMS
                if isinstance(self.scoring.get(d), (int, float))]
        return round(sum(vals) / len(vals), 2) if vals else 0.0


@dataclass
class ReadinessReport:
    """岗位可插件化就绪度：分数 + 评级 + 缺口清单（缺什么给什么）"""
    role_name: str = ""
    unit_id: str = ""
    score: float = 0.0
    grade: str = "D"
    label: str = ""
    factors: Dict[str, float] = field(default_factory=dict)
    gaps: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "role_name": self.role_name, "unit_id": self.unit_id,
            "score": self.score, "grade": self.grade, "label": self.label,
            "factors": self.factors, "gaps": self.gaps,
        }


@dataclass
class RoleProfile:
    """人工画像基线（data/role-profiles/*.yaml 的一个 role 条目）"""
    role: str
    analysis: Dict[str, Any] = field(default_factory=dict)
    persona: Dict[str, Any] = field(default_factory=dict)
    plugin: Dict[str, Any] = field(default_factory=dict)
    workflow: Dict[str, Any] = field(default_factory=dict)
    stakeholders: StakeholderChain = field(default_factory=StakeholderChain)
    capability: CapabilityProfile = field(default_factory=CapabilityProfile)
    source: str = ""

    def dimension(self, name: str):
        return getattr(self, name, None)


def _chain_values(card, field: str) -> List[str]:
    """优先用归一后的说法（统一叫法），没有则回落到原始值。"""
    refs = (card.chain_refs or {}).get(field) or []
    return [str(r.get("value", "")) for r in refs if r.get("value")]


@dataclass
class RoleCard:
    """
    岗位画像卡：渲染产物（画像基线 × 注册表岗位 × 工作流模板）。
    这是主链路真正消费的对象：路由加权 / 上下文注入 / playbook 执行。
    """
    unit_id: str
    industry: str
    role: str
    prefix: str = ""
    description: str = ""
    keywords: List[str] = field(default_factory=list)
    profile: Optional[RoleProfile] = None
    workflows: List[Dict[str, Any]] = field(default_factory=list)
    plugin_artifacts: List[Dict[str, Any]] = field(default_factory=list)
    activation: Dict[str, Any] = field(default_factory=dict)
    readiness: Optional[ReadinessReport] = None
    sources: List[str] = field(default_factory=list)
    # M11.1 归一后的利益链条：链上只留行业类，具体公司靠 index 现查，不落库
    chain_refs: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    # 所属行业的战略视图（钱为什么在这、AI 该站哪一段）。粒度只到岗位/角色：
    # 它给的是判断，不是工序——工序由 AI 上岗认领职责后自己补。
    industry_view: Dict[str, Any] = field(default_factory=dict)

    # -------------------------------------------------- 查询便捷方法
    def capability(self) -> CapabilityProfile:
        return self.profile.capability if self.profile else CapabilityProfile()

    def chain(self) -> StakeholderChain:
        return self.profile.stakeholders if self.profile else StakeholderChain()

    def workflow_by_id(self, wf_id: str) -> Optional[Dict[str, Any]]:
        for wf in self.workflows:
            if wf.get("id") == wf_id:
                return wf
        return None

    def default_workflow(self) -> Optional[Dict[str, Any]]:
        if not self.workflows:
            return None
        for wf in self.workflows:
            if wf.get("default"):
                return wf
        return self.workflows[0]

    def playbook(self, wf_id: str = "") -> List[WorkflowStep]:
        """取某工作流的步骤序列（默认为 default 流），供 Agent 按序执行。"""
        wf = self.workflow_by_id(wf_id) if wf_id else self.default_workflow()
        if not wf:
            return []
        steps = []
        for raw in wf.get("steps", []) or []:
            if not isinstance(raw, dict):
                continue
            steps.append(WorkflowStep(
                id=str(raw.get("id", "")),
                name=str(raw.get("name", "")),
                agent_role=str(raw.get("agent_role", "") or self.role),
                playbook=str(raw.get("playbook", "")),
                preconditions=[str(x) for x in raw.get("preconditions", []) or []],
                outputs=[str(x) for x in raw.get("outputs", []) or []],
                verify=[str(x) for x in raw.get("verify", []) or []],
                runtime=str(raw.get("runtime", "agent")),
            ))
        return steps

    # -------------------------------------------------- 上下文注入（M10）
    def to_context_block(self, wf_id: str = "") -> str:
        """
        渲染成可注入提示词的稳定文本块（M10 静态层素材）。
        要求：内容只由画像卡数据决定，同岗位同版本输出恒定 → 缓存键稳定。
        """
        p = self.profile
        lines = [f"## 岗位卡: {self.role}（{self.unit_id} / {self.industry}）",
                 f"- 前缀: {self.prefix}"]
        if p:
            a = p.analysis
            if a.get("mission"):
                lines.append(f"- 使命: {a['mission']}")
            if a.get("deliverables"):
                lines.append(f"- 交付物: {'、'.join(map(str, a['deliverables']))}")
            if p.persona.get("tone"):
                lines.append(f"- 语气: {p.persona['tone']}")
            if p.persona.get("constraints"):
                lines.append(f"- 边界: {'；'.join(map(str, p.persona['constraints']))}")
            cap = p.capability
            if cap.core:
                lines.append(f"- 核心能力: {'、'.join(cap.core)}")
            ch = p.stakeholders
            if ch.upstream:
                lines.append(f"- 上游输入: {'、'.join(_chain_values(self, 'upstream') or ch.upstream)}")
            if ch.downstream:
                lines.append(f"- 下游承接: {'、'.join(_chain_values(self, 'downstream') or ch.downstream)}")
            if ch.blockers:
                lines.append(f"- 常见阻碍: {'、'.join(ch.blockers)}")
        # 行业大局：岗位卡说"这个岗位怎么干"，这一段说"这个行业的钱在哪"。
        # 缺了它，AI 会认真把一个不赚钱的环节做到极致——不是能力问题，
        # 是没人告诉它行业长什么样。
        #
        # 刻意**不在 `if p:` 里面**：行业判断属于「行业」，不属于「这个人的画像」。
        # 早先它跟着画像一起被挡，于是没有画像基线的岗位卡静默丢掉行业判断，
        # 而那条断言（test_card_without_industry_view_still_renders）想表达的
        # 恰恰是"少了画像也不该少行业"。当前 51 张卡都有画像，所以是潜伏的。
        iv = self.industry_view or {}
        if iv:
            if iv.get("position"):
                lines.append(f"- 行业位置: {iv['position']}")
            if iv.get("profit_pool"):
                pools = "；".join(f"{it.get('where')}（{it.get('why')}）"
                                 for it in iv["profit_pool"] if isinstance(it, dict))
                if pools:
                    lines.append(f"- 利润池: {pools}")
            if iv.get("risks"):
                lines.append(f"- 行业风险: {'、'.join(iv['risks'])}")
            if iv.get("ai_boundary"):
                lines.append(f"- AI 边界: {iv['ai_boundary']}")
            if iv.get("human_decides"):
                lines.append(f"- 必须人定: {'、'.join(iv['human_decides'])}")
            if iv.get("ai_fills"):
                lines.append(f"- 可交给 AI 补: {'、'.join(iv['ai_fills'])}")
        steps = self.playbook(wf_id)
        if steps:
            lines.append("- 工作流:")
            for i, s in enumerate(steps, 1):
                lines.append(f"  {i}. {s.name or s.id}（{s.runtime}）"
                             + (f" → {s.playbook}" if s.playbook else ""))
        return "\n".join(lines)
