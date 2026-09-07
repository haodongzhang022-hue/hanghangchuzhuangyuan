"""M9 秘书并发归属与冲突仲裁（OwnershipGuard）

背景：Issue #5 秘书分工机制中，多 Agent / 多秘书需在"层级树"里协作推进同一任务，
但可能同时读写同一张 StateCard（如两个秘书都想把某任务标 done / 挂依赖）。

论文 SKILL.state 亦明示限制："多 Agent 并发写状态还需要确定性的冲突处理"。
本模块补齐秘书机制在多秘书协作场景的最后一块拼图：
- **归属声明**：每张状态卡 owner 为责任秘书坑位，claim/release 显式声明占用；
- **乐观并发仲裁**：写回须携带其"读到的 base_version"，若与最新不符(他人已改)，
  抛 StateConflict 拒绝覆盖——结果确定，不静默丢更新；
- **租约写锁**：可为某卡加临时写租约(持有者+过期)，防止两秘书同时改写；
- 全程兼容既有 StateManager：仅新增受控写入口，不改变原有无并发参数调用路径。
"""
from __future__ import annotations

import json
import os
import time
from typing import List, Optional

from .models import StateCard, TaskRecord
from .manager import StateManager


class StateConflict(Exception):
    """确定性并发冲突：同一张 StateCard 被并发秘书修改。

    携带冲突双方信息，供上层确定性处置（重读最新 / 回滚 / 人工裁决）。
    """

    def __init__(self, message: str, *, session_id: str = "",
                 expected_version: Optional[int] = None,
                 actual_version: Optional[int] = None,
                 current_owner: str = "", requester: str = ""):
        super().__init__(message)
        self.session_id = session_id
        self.expected_version = expected_version
        self.actual_version = actual_version
        self.current_owner = current_owner
        self.requester = requester


class OwnershipDenied(Exception):
    """归属越权：请求秘书非该卡 owner，且未获授权，拒绝写入。"""


class CardLease:
    """一张 StateCard 的临时写租约（占用声明）。"""

    def __init__(self, holder: str, ttl_sec: float = 300.0):
        self.holder = holder
        self.acquired_at = time.time()
        self.until = self.acquired_at + ttl_sec

    def is_expired(self) -> bool:
        return time.time() > self.until

    def to_dict(self) -> dict:
        return {
            "holder": self.holder,
            "acquired_at": self.acquired_at,
            "until": self.until,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Optional["CardLease"]:
        if not isinstance(data, dict) or not data.get("holder"):
            return None
        try:
            lease = cls(holder=data["holder"])
            lease.acquired_at = float(data.get("acquired_at", lease.acquired_at))
            lease.until = float(data.get("until", lease.acquired_at + 300))
            return lease
        except (TypeError, ValueError):
            return None


class OwnershipGuard:
    """秘书并发写同一状态的确定性归属 + 冲突仲裁。

    用法（在秘书/执行 agent 侧）：
        guard = OwnershipGuard(session_id, state_manager, secretary="secre_a")
        guard.claim()                                  # 声明归属(占用卡)
        guard.guarded_add_task("写报告", base_version=guard.version())  # 携带读到的版本写
        guard.release()                                # 释放归属

    任一秘书（含非 owner）也可以只读；只有 owner(或获授权者)可写。
    """

    LOCK_SUFFIX = ".owner.json"

    def __init__(self, session_id: str, state_manager: StateManager,
                 secretary: str = "secretary"):
        if not state_manager.get_card(session_id):
            raise ValueError(f"session 不存在，需先创建 StateCard: {session_id}")
        self.session_id = session_id
        self.sm = state_manager
        self.secretary = secretary
        self._data_dir = state_manager.data_dir

    # ---- 只读 ----

    def get_card(self) -> Optional[StateCard]:
        return self.sm.get_card(self.session_id)

    def version(self) -> int:
        card = self.sm.get_card(self.session_id)
        return card.version if card else 0

    def current_owner(self) -> str:
        card = self.sm.get_card(self.session_id)
        return (card.owner or "") if card else ""

    # ---- 归属声明/释放 ----

    def claim(self, force: bool = False) -> str:
        """声明本秘书为该卡的 owner。
        force=True：强制抢占(覆盖原 owner)；默认若已被他人占用则拒绝。
        返回占用成功的秘书坑位名。
        """
        lease = self._load_lease()
        if lease and lease.holder != self.secretary and not lease.is_expired():
            if not force:
                raise StateConflict(
                    f"卡 {self.session_id} 已被秘书 {lease.holder} 写租约占用，"
                    f"拒绝 {self.secretary} 抢占。可用 force=True 强制抢占或等待租约过期。",
                    session_id=self.session_id, current_owner=lease.holder,
                    requester=self.secretary)
        self._store_lease(CardLease(self.secretary))
        self._set_owner(self.secretary)
        return self.secretary

    def release(self) -> None:
        """释放本秘书对卡的归属与写租约(仅 owner 或租约持有者可释放)。"""
        lease = self._load_lease()
        if lease and lease.holder == self.secretary:
            self._clear_lease()
        card = self.sm.get_card(self.session_id)
        if card and card.owner == self.secretary:
            card.owner = ""
            card.version += 1
            self.sm.save_card(card)

    def is_owner(self) -> bool:
        return self.current_owner() == self.secretary

    # ---- 乐观并发受控写 ----

    def guarded_add_task(self, title: str, base_version: Optional[int] = None,
                         objective: str = "", cur_dir: str = "",
                         files: Optional[List[str]] = None,
                         depends_on: Optional[List[str]] = None,
                         tools: Optional[List[str]] = None,
                         task_type: str = "normal",
                         content_ref: Optional[str] = None,
                         **kwargs) -> TaskRecord:
        """归属 + 乐观版本受控的新增任务写。"""
        self._authorize()
        self._check_version(base_version)
        task = self.sm.add_task(
            self.session_id, title, objective=objective, cur_dir=cur_dir,
            files=files, depends_on=depends_on, tools=tools,
            task_type=task_type, content_ref=content_ref, **kwargs)
        if task is None:
            raise StateConflict("卡不存在或已被删除", session_id=self.session_id,
                                requester=self.secretary)
        return task

    def guarded_update_task_state(self, task_id: str, state: str,
                                  base_version: Optional[int] = None) -> bool:
        self._authorize()
        self._check_version(base_version)
        return self.sm.update_task_state(self.session_id, task_id, state)

    def guarded_update_task_fields(self, task_id: str, base_version: Optional[int] = None,
                                   **fields) -> bool:
        self._authorize()
        self._check_version(base_version)
        return self.sm.update_task_fields(self.session_id, task_id, **fields)

    # ---- 内部 ----

    def _authorize(self) -> None:
        """写权限预检：仅 owner 或租约持有者可写。"""
        lease = self._load_lease()
        if lease and lease.holder != self.secretary and not lease.is_expired():
            # 卡正被他人租约占用，非 owner 秘书不得写
            owner = self.current_owner()
            if owner and owner != self.secretary:
                raise OwnershipDenied(
                    f"秘书 {self.secretary} 无权写卡 {self.session_id}："
                    f"owner={owner}，租约持有者={lease.holder}")
        # 若卡尚未 claim(owner 为空)，首个尝试写的秘书视为隐式取得该卡维护权
        card = self.sm.get_card(self.session_id)
        if card and not card.owner:
            card.owner = self.secretary
            self.sm.save_card(card)

    def _check_version(self, base_version: Optional[int]) -> None:
        """乐观并发仲裁：写回须携带"读到的版本"，若已被他人改过则冲突。"""
        if base_version is None:
            return  # 未携带版本 → 放弃乐观检测(兼容旧用法)
        current = self.version()
        if base_version != current:
            raise StateConflict(
                f"乐观并发冲突：卡 {self.session_id} 版本已从 {base_version} 变为 {current}，"
                f"秘书 {self.secretary} 基于旧版本写入被拒，请重读最新后重试。",
                session_id=self.session_id, expected_version=base_version,
                actual_version=current, requester=self.secretary)

    def _set_owner(self, owner: str) -> None:
        card = self.sm.get_card(self.session_id)
        if card:
            card.owner = owner
            card.version += 1
            self.sm.save_card(card)

    # ---- 租约持久化到 data/state/<session>.owner.json ----

    def _lease_path(self) -> str:
        return os.path.join(self._data_dir, f"{self.session_id}{self.LOCK_SUFFIX}")

    def _load_lease(self) -> Optional[CardLease]:
        path = self._lease_path()
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return CardLease.from_dict(json.load(f))
        except Exception:
            return None

    def _store_lease(self, lease: CardLease) -> None:
        with open(self._lease_path(), "w", encoding="utf-8") as f:
            json.dump(lease.to_dict(), f, ensure_ascii=False, indent=2)

    def _clear_lease(self) -> None:
        path = self._lease_path()
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
