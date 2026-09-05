"""自动打标引擎（Auto Label Engine）

参考自 dongjiagoushi / youxikaifaxilieagent 的自动打标机制。
在 Issue/PR/评审等事件到达时自动打标，无需人工记得去调。
"""
from __future__ import annotations

import json
import os
import time
from typing import Dict, List, Optional


class AutoLabelEngine:
    """
    事件驱动自动打标：
    根据事件类型自动决定应打/应刷的标签。
    """

    # 事件 → 标签映射规则
    EVENT_RULES = {
        "issue.open": {"label": "待处理", "priority": "P1"},
        "issue.update": {"action": "refresh"},
        "issue.close": {"label": "已关闭", "action": "remove_open"},
        "issue.reopen": {"label": "已重新打开", "action": "refresh"},
        "pr.open": {"label": "待评审", "priority": "P1"},
        "pr.merged": {"label": "已合并", "action": "close"},
        "pr.merged+done": {"label": "已完成"},
        "review.need_fix": {"label": "需修复", "action": "block"},
        "review.pass": {"label": "评审通过"},
        "review.merge": {"label": "适合合并"},
        "review.changes_requested": {"label": "需修改", "action": "block"},
        "task.done": {"label": "已完成"},
        "progress.advance": {"action": "refresh_progress"},
        "sentinel.alert": {"label": "停滞"},
    }

    # 进度标签（人可读层）
    PROGRESS_LABELS = {
        0: "0%", 5: "5%", 10: "10%", 15: "15%", 20: "20%",
        25: "25%", 30: "30%", 35: "35%", 40: "40%", 45: "45%",
        50: "50%", 55: "55%", 60: "60%", 65: "65%", 70: "70%",
        75: "75%", 80: "80%", 85: "85%", 90: "90%", 95: "95%",
        100: "100%",
    }

    def __init__(self, label_store: Optional[str] = None):
        self.label_store = label_store or os.path.join(
            os.getcwd(), "data", "label-events.jsonl")
        os.makedirs(os.path.dirname(self.label_store), exist_ok=True)

    def apply_event(self, event: str, entity_id: str = "", extra: Dict = None) -> Dict:
        """
        根据事件类型返回应打的标签和动作。
        """
        extra = extra or {}
        rule = self.EVENT_RULES.get(event, {})

        # 无规则：静默放行
        if not rule:
            return {"action": "noop", "event": event, "entity": entity_id}

        labels_to_add = []
        if "label" in rule:
            labels_to_add.append(rule["label"])
        if "priority" in rule:
            labels_to_add.append(rule["priority"])

        # 进度百分比（对非数字做类型防御，避免 int() 抛 ValueError）
        if "progress" in extra:
            try:
                pct = int(extra["progress"])
            except (TypeError, ValueError):
                pct = None
            if pct is not None and 0 <= pct <= 100:
                nearest = min(self.PROGRESS_LABELS.keys(), key=lambda x: abs(x - pct))
                labels_to_add.append(f"progress_{self.PROGRESS_LABELS[nearest]}")

        result = {
            "action": rule.get("action", "add"),
            "event": event,
            "entity": entity_id,
            "labels": labels_to_add,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

        self._log(result)
        return result

    def _log(self, event: Dict):
        """写入事件日志"""
        with open(self.label_store, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    def summary(self) -> str:
        """返回已记录事件的摘要"""
        if not os.path.exists(self.label_store):
            return "暂无标签事件记录"
        with open(self.label_store, "r", encoding="utf-8") as f:
            events = [json.loads(line) for line in f if line.strip()]
        return f"已记录 {len(events)} 条标签事件"
