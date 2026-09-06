"""M9 层级向上提交协议：下级秘书 → 上级秘书 汇总"""
from __future__ import annotations

import json
import os
import time
from typing import Dict, List, Optional

from .models import StateCard, TaskRecord, TaskState


class HierarchySubmitter:
    """
    M9 层级向上提交：
    下级秘书维护局部状态卡（StateCard），
    需要向上级提交时，只传"结构化汇总"而非全量原文。

    提交内容 = 下级 StateCard 的 summarize_for_upstream() 结果：
    - 目标、进度、任务编号清单、content_refs
    - 不含原文正文
    """

    def __init__(self, data_dir: Optional[str] = None):
        self.data_dir = data_dir or os.path.join(os.getcwd(), "data", "state")
        os.makedirs(self.data_dir, exist_ok=True)

    def submit_up(self, card: StateCard,
                  upstream_session: str = None) -> dict:
        """
        将下级秘书的 StateCard 向上级提交汇总。
        返回提交记录（含已提交的汇总 + 时间戳），并写落盘。
        """
        summary = card.summarize_for_upstream()
        if upstream_session:
            card.upstream = upstream_session
        else:
            upstream_session = card.upstream or "root"

        submission = {
            "from_session": card.session_id,
            "from_role": card.role_name,
            "to_session": upstream_session,
            "submitted_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "payload": summary,
        }
        self._record_submission(submission)
        return submission

    def aggregate_from_downstreams(self, parent_card: StateCard,
                                   children: List[StateCard]) -> dict:
        """
        上级秘书聚合多个下级的提交。
        上级看到的是各下级的"汇总快照"，不携带下级全量上下文。
        """
        aggregated = {
            "parent_session": parent_card.session_id,
            "parent_objective": parent_card.objective,
            "aggregated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "children": [],
        }
        for child in children:
            summary = child.summarize_for_upstream()
            aggregated["children"].append({
                "session_id": child.session_id,
                "role": child.role_name,
                "objective": child.objective,
                "task_count": summary["task_count"],
                "done_count": summary["done_count"],
                "blocked_count": summary["blocked_count"],
                "in_progress_count": summary["in_progress_count"],
                "content_refs": summary["content_refs"],
            })
            # 记录上下游关系
            if child.session_id not in parent_card.downstream:
                parent_card.downstream.append(child.session_id)
            child.upstream = parent_card.session_id

        return aggregated

    def _record_submission(self, submission: dict):
        """记录一次提交到 data/state/submissions.log"""
        log_path = os.path.join(self.data_dir, "submissions.jsonl")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(submission, ensure_ascii=False) + "\n")

    def list_submissions(self, session_id: str = None) -> List[dict]:
        """查看提交记录"""
        log_path = os.path.join(self.data_dir, "submissions.jsonl")
        if not os.path.exists(log_path):
            return []
        records = []
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if session_id and rec.get("from_session") != session_id:
                    continue
                records.append(rec)
        return records
