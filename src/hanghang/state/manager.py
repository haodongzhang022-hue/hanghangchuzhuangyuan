"""M9 状态管理器：StateCard 的生命周期管理"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Dict, List, Optional

from .models import StateCard, TaskRecord, TaskState, FoldState

# session_id 白名单：仅允许字母/数字/下划线/短横线
_SESSION_ID_PATTERN = re.compile(r'^[A-Za-z0-9_-]+$')


class StateManager:
    """
    M9 状态管理器（StateManager）：
    - 每个 session/对话 分配一张 StateCard
    - 管理 StateCard 的创建/读取/更新/删除
    - 落盘到 data/state/ 目录（JSON）
    - 提供折叠/展开查询
    """

    def __init__(self, data_dir: Optional[str] = None):
        self.data_dir = data_dir or os.path.join(os.getcwd(), "data", "state")
        os.makedirs(self.data_dir, exist_ok=True)

    # ---- 生命周期管理 ----

    def create_card(self, session_id: str, objective: str = "",
                    unit_id: str = "", role_name: str = "secretary",
                    **kwargs) -> StateCard:
        """创建一张新的 StateCard"""
        self._validate_session_id(session_id)
        card = StateCard(
            session_id=session_id,
            unit_id=unit_id,
            role_name=role_name,
            objective=objective,
            **kwargs,
        )
        self.save_card(card)
        return card

    def get_card(self, session_id: str) -> Optional[StateCard]:
        """按会话ID读取 StateCard"""
        if not self._is_valid_session_id(session_id):
            return None
        path = self._card_path(session_id)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return StateCard.from_dict(data)
        except Exception:
            return None

    def get_or_create(self, session_id: str, objective: str = "",
                      unit_id: str = "", role_name: str = "secretary") -> StateCard:
        """获取已有卡，不存在则创建"""
        card = self.get_card(session_id)
        if card is None:
            card = self.create_card(session_id, objective, unit_id, role_name)
        return card

    def delete_card(self, session_id: str) -> bool:
        """删除一张 StateCard"""
        if not self._is_valid_session_id(session_id):
            return False
        path = self._card_path(session_id)
        if os.path.exists(path):
            os.remove(path)
            return True
        return False

    def list_cards(self) -> List[StateCard]:
        """列出所有 StateCard"""
        cards = []
        for f in os.listdir(self.data_dir):
            if f.endswith(".json"):
                path = os.path.join(self.data_dir, f)
                try:
                    with open(path, "r", encoding="utf-8") as fh:
                        data = json.load(fh)
                    cards.append(StateCard.from_dict(data))
                except Exception:
                    continue
        return cards

    # ---- 任务操作 ----

    def add_task(self, session_id: str, title: str,
                 objective: str = "", cur_dir: str = "",
                 files: Optional[List[str]] = None,
                 depends_on: Optional[List[str]] = None,
                 tools: Optional[List[str]] = None,
                 task_type: str = "normal",
                 content_ref: Optional[str] = None,
                 **kwargs) -> Optional[TaskRecord]:
        """新增一个任务到 StateCard"""
        card = self.get_card(session_id)
        if card is None:
            return None
        task = card.add_task(
            title=title,
            objective=objective,
            cur_dir=cur_dir,
            files_touched=files or [],
            depends_on=depends_on or [],
            tools_called=tools or [],
            task_type=task_type,
            content_ref=content_ref,
            **kwargs,
        )
        self.save_card(card)
        return task

    def update_task_state(self, session_id: str, task_id: str,
                          state: str) -> bool:
        """更新任务状态（带迁移校验）"""
        card = self.get_card(session_id)
        if card is None:
            return False
        ok = card.update_task(task_id, state=state)
        if ok:
            self.save_card(card)
        return ok

    def update_task_fields(self, session_id: str, task_id: str,
                           **fields) -> bool:
        """更新任务的任意字段"""
        card = self.get_card(session_id)
        if card is None:
            return False
        ok = card.update_task(task_id, **fields)
        if ok:
            self.save_card(card)
        return ok

    def fold_task(self, session_id: str, task_id: str) -> bool:
        """折叠指定任务（默认所有任务都是折叠态，此处用于显式折叠）"""
        return self.update_task_fields(session_id, task_id, fold=FoldState.COLLAPSED.value)

    def expand_task(self, session_id: str, task_id: str) -> bool:
        """展开指定任务（仅当前执行态/交付任务展开）"""
        return self.update_task_fields(session_id, task_id, fold=FoldState.EXPANDED.value)

    # ---- 查询 ----

    def get_expanded_tasks(self, session_id: str) -> List[TaskRecord]:
        """获取当前展开的任务列表"""
        card = self.get_card(session_id)
        if card is None:
            return []
        return [t for t in card.tasks if t.fold == FoldState.EXPANDED.value]

    def get_collapsed_tasks(self, session_id: str) -> List[TaskRecord]:
        """获取当前折叠的任务列表"""
        card = self.get_card(session_id)
        if card is None:
            return []
        return [t for t in card.tasks if t.fold == FoldState.COLLAPSED.value]

    def get_active_task(self, session_id: str) -> Optional[TaskRecord]:
        """获取当前正在执行的任务（第一个 in_progress）"""
        card = self.get_card(session_id)
        if card is None:
            return None
        for t in card.tasks:
            if t.state == TaskState.IN_PROGRESS.value:
                return t
        return None

    def get_deliverable_tasks(self, session_id: str) -> List[TaskRecord]:
        """获取末端交付任务（task_type=deliverable 且 fold=expanded）"""
        card = self.get_card(session_id)
        if card is None:
            return []
        return [t for t in card.tasks
                if t.task_type == "deliverable"
                and t.fold == FoldState.EXPANDED.value]

    # ---- 层级 ----

    def set_upstream(self, session_id: str, upstream_session: str) -> bool:
        """设置上级秘书引用"""
        card = self.get_card(session_id)
        if card is None:
            return False
        card.upstream = upstream_session
        self.save_card(card)
        return True

    def add_downstream(self, session_id: str, downstream_session: str) -> bool:
        """添加下级秘书引用"""
        card = self.get_card(session_id)
        if card is None:
            return False
        if downstream_session not in card.downstream:
            card.downstream.append(downstream_session)
        self.save_card(card)
        return True

    # ---- 公开持久化接口 ----

    def save_card(self, card: StateCard) -> None:
        """将 StateCard 持久化到磁盘（供 CLI 等外部调用）"""
        self._validate_session_id(card.session_id)
        self._save(card)

    def apply_fold_policy(self, session_id: str,
                          current_task_id: str = None) -> Optional[StateCard]:
        """公开的折叠策略入口：对指定 session 执行自动折叠并持久化"""
        from .fold_engine import FoldEngine
        card = self.get_card(session_id)
        if card is None:
            return None
        engine = FoldEngine(card.session_id)
        card = engine.auto_fold_policy(card, current_task_id=current_task_id)
        self.save_card(card)
        return card

    # ---- 内部 ----

    @staticmethod
    def _is_valid_session_id(session_id: str) -> bool:
        """校验 session_id 是否合法（仅 [A-Za-z0-9_-]）"""
        if not isinstance(session_id, str) or not session_id:
            return False
        return bool(_SESSION_ID_PATTERN.match(session_id))

    @classmethod
    def _validate_session_id(cls, session_id: str) -> None:
        """校验 session_id，非法则抛 ValueError"""
        if not cls._is_valid_session_id(session_id):
            raise ValueError(
                f"非法 session_id: {session_id!r}。仅允许字母/数字/下划线/短横线 "
                f"([A-Za-z0-9_-])，防止路径穿越。"
            )

    def _card_path(self, session_id: str) -> str:
        self._validate_session_id(session_id)
        return os.path.join(self.data_dir, f"{session_id}.json")

    def _save(self, card: StateCard):
        path = self._card_path(card.session_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(card.to_dict(), f, ensure_ascii=False, indent=2)
