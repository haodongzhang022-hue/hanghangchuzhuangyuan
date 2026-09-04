"""M5 跨单元交接总线"""
from __future__ import annotations

import json
import os
import time
from typing import List, Optional

from .models import HandoffCard


class HandoffBus:
    """
    M5 跨单元交接总线：
    管理跨行业/跨岗位交接卡的生命周期。
    交接卡采用 JSON 格式存储，便于后续扩展为异步消息。
    """

    def __init__(self, data_dir: Optional[str] = None):
        self.data_dir = data_dir or os.path.join(os.getcwd(), "data", "handoffs")
        os.makedirs(self.data_dir, exist_ok=True)

    def create_handoff(self, source_unit: str, target_unit: str,
                       intent: str, context: str = "") -> HandoffCard:
        """创建一张交接卡"""
        card_id = f"{source_unit}-{target_unit}-{int(time.time())}"
        card = HandoffCard(
            id=card_id,
            source_unit=source_unit,
            target_unit=target_unit,
            intent=intent,
            context=context,
            created_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        self._save(card)
        return card

    def get(self, card_id: str) -> Optional[HandoffCard]:
        """按 ID 读取交接卡"""
        path = os.path.join(self.data_dir, f"{card_id}.json")
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return HandoffCard(**data)

    def update_status(self, card_id: str, status: str) -> bool:
        """更新交接卡状态"""
        card = self.get(card_id)
        if not card:
            return False
        card.status = status
        self._save(card)
        return True

    def list_pending(self) -> List[HandoffCard]:
        """列出所有待处理交接卡"""
        pending = []
        for f in os.listdir(self.data_dir):
            if f.endswith(".json"):
                card = self.get(f[:-5])
                if card and card.status == "created":
                    pending.append(card)
        return pending

    def _save(self, card: HandoffCard):
        if not card.id:
            card.id = f"{card.source_unit}-{card.target_unit}-{int(time.time())}"
        path = os.path.join(self.data_dir, f"{card.id}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "id": card.id,
                "source_unit": card.source_unit,
                "target_unit": card.target_unit,
                "intent": card.intent,
                "context": card.context,
                "status": card.status,
                "created_at": card.created_at,
            }, f, ensure_ascii=False, indent=2)
