"""工作流渲染器（M11）：模板 + 岗位覆盖 → 可执行步骤序列

设计意图：岗位的工作流不该每个行业重写一遍。
  - 通用工序（接单→取上下文→主作业→自检→交付→交接）沉到 data/workflow-templates/
  - 岗位只写 override，覆盖命名/playbook/role，并声明 runtime(agent|n8n|code)
这样「很多岗位形成流程或 n8n 或纯代码化的流程」就是同一份数据的三种导出形态。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _merge_step_list(base: List[Any], override: List[Any]) -> List[Any]:
    """步骤列表合并：以 id 为主键逐条覆盖，未匹配的追加。

    这样岗位只写「要改的那几步」，模板新增步骤也能自动继承——
    否则一旦用整表覆盖，模板演进就必须回头改每个岗位。
    """
    merged: List[Any] = []
    by_id: Dict[str, Any] = {}
    for item in base:
        if isinstance(item, dict) and item.get("id"):
            by_id[str(item["id"])] = item
        merged.append(item)
    for item in override:
        if isinstance(item, dict) and item.get("id"):
            sid = str(item["id"])
            if sid in by_id:
                idx = merged.index(by_id[sid])
                by_id[sid] = deep_merge(by_id[sid], item)
                merged[idx] = by_id[sid]
                continue
        merged.append(item)
    return merged


def deep_merge(base: Any, override: Any, key: str = "") -> Any:
    """深合并：dict 递归、steps 按 id 覆盖、其余覆盖。

    - steps 列表：岗位可用 dict（{步骤id: 覆盖}）或 list 声明，均以 id 为主键
      逐条覆盖（见 _merge_step_list）——模板新增步骤能自动继承，不必回头改每个岗位
    - 其余列表：整体覆盖（不做逐元素合并，避免半张列表对不上）
    """
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for k, v in override.items():
            merged[k] = v if k not in base else deep_merge(base[k], v, k)
        return merged
    if key == "steps":
        if isinstance(base, list) and isinstance(override, dict):
            # dict 形态：{id: {...}} → 转成带 id 的列表再合并
            patch = [dict({"id": sid}, **(v or {})) if isinstance(v, dict) else {"id": sid}
                     for sid, v in override.items()]
            return _merge_step_list(base, patch)
        if isinstance(base, list) and isinstance(override, list):
            return _merge_step_list(base, override)
    if override is None:
        return base
    return override


class WorkflowRenderer:
    """把工作流模板渲染成具体岗位的工作流（含步骤 playbook）。"""

    def __init__(self, templates: Optional[Dict[str, dict]] = None):
        self.templates = templates or {}

    def register_template(self, template_id: str, data: dict) -> None:
        if template_id:
            self.templates[template_id] = data or {}

    def render(self, spec: dict, role: str, default_flow: str = "") -> Optional[dict]:
        """
        spec 形如:
          {template: standard-delivery, id: wf-main, name: 主流程, default: true,
           override: {steps: {...}}}
        返回渲染后的工作流 dict（含 steps 列表）。模板缺失时降级为 min-flow。
        """
        if not isinstance(spec, dict):
            return None
        template_id = str(spec.get("template", "") or default_flow or "min-flow")
        template = self.templates.get(template_id) or {}
        if not template:
            # 模板缺失 → 降级到 min-flow，并如实把"降级了"记在模板名上，
            # 让 reviewer/评测能看见哪条流程其实是兜底跑起来的
            template = self.templates.get("min-flow") or MIN_FLOW
            template_id = f"min-flow(缺失:{template_id})"
        merged = deep_merge(template.get("flow", {}), spec.get("override", {}) or {})

        wf = {
            "id": str(spec.get("id", "") or merged.get("id", "") or template_id),
            "name": str(spec.get("name", "") or merged.get("name", "") or template_id),
            "default": bool(spec.get("default", False)),
            "template": template_id,
            "trigger": spec.get("trigger", merged.get("trigger", "")),
            "handoff_out": spec.get("handoff_out", merged.get("handoff_out", "")),
            "steps": [],
        }
        for raw in merged.get("steps", []) or []:
            if not isinstance(raw, dict):
                continue
            step = dict(raw)
            step["agent_role"] = str(step.get("agent_role", "") or role)
            step["id"] = str(step.get("id", ""))
            wf["steps"].append(step)
        return wf

    def render_all(self, specs: List[dict], role: str,
                   default_flow: str = "") -> List[dict]:
        out = []
        for spec in specs or []:
            wf = self.render(spec, role, default_flow)
            if wf:
                out.append(wf)
        # 保证至少有一条 default 流，便于 playbook() 直接取用
        if out and not any(w.get("default") for w in out):
            out[0]["default"] = True
        return out


MIN_FLOW: dict = {
    "id": "min-flow",
    "description": "最小可用流：模板缺失时的兜底工序，保证岗位卡仍能被调度",
    "flow": {
        "name": "最小流程",
        "steps": [
            {"id": "intake", "name": "接单", "playbook": "确认诉求与交付物边界",
             "outputs": ["诉求备忘"], "verify": ["交付物与验收口径已确认"]},
            {"id": "work", "name": "主作业", "playbook": "按岗位核心能力产出交付物",
             "outputs": ["交付物"], "verify": ["交付物自检通过"]},
            {"id": "deliver", "name": "交付", "playbook": "按岗位画像语气输出并附依据",
             "outputs": ["交付说明"], "verify": ["结论与依据可回溯"]},
        ],
    },
}
