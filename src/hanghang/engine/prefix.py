"""M3 稳定前缀档案库"""
from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

from .models import IndustryUnit


class PrefixArchive:
    """
    M3 稳定前缀档案库：
    固化各行业/岗位的稳定前缀模板，禁止运行期改写。
    核心约束：一个 session = 一个行业 = 一套稳定前缀。
    """

    def __init__(self, archive_file: Optional[str] = None):
        self.archive_file = archive_file or os.path.join(
            os.getcwd(), "data", "prefix-archive.json")
        os.makedirs(os.path.dirname(self.archive_file), exist_ok=True)
        self._archive: Dict[str, dict] = self._load()

    def _load(self) -> dict:
        if os.path.exists(self.archive_file):
            try:
                with open(self.archive_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def register_unit(self, unit: IndustryUnit, persist: bool = True):
        """注册/更新一个单元的稳定前缀档案。

        参数:
            persist: 是否立即持久化到磁盘。为 False 时仅更新内存，不触发文件写入。
        默认 persist=True 保持与历史行为一致（CLI 入口在启动时注册并回写磁盘）。
        Web 只读路径应传入 persist=False 以避免 GET 请求写文件的副作用。
        """
        entry = {
            "unit_id": unit.unit_id,
            "industry": unit.industry,
            "role_prefixes": {
                r.name: {
                    "prefix": r.prefix,
                    "composite": r.composite,
                    "handoff": r.handoff,
                }
                for r in unit.roles
            },
            "rule": "one_session_one_industry_fixed_prefixes",
        }
        self._archive[unit.unit_id] = entry
        if persist:
            self._save()

    def get_archive(self) -> Dict[str, dict]:
        """获取全量前缀档案（只读视图）。"""
        return dict(self._archive)

    def get_unit_prefixes(self, unit_id: str) -> Optional[List[str]]:
        """获取某单元的全部岗位稳定前缀"""
        entry = self._archive.get(unit_id)
        if not entry:
            return None
        return [p["prefix"] for p in entry.get("role_prefixes", {}).values()]

    def get_role_prefix(self, unit_id: str, role_name: str) -> Optional[str]:
        """获取某单元某岗位的稳定前缀"""
        entry = self._archive.get(unit_id)
        if not entry:
            return None
        role = entry.get("role_prefixes", {}).get(role_name)
        return role["prefix"] if role else None

    def validate_stable(self, unit_id: str) -> bool:
        """校验单元前缀档案是否稳定（无突变）"""
        # 在会话中前缀不应被改写。当前实现天然不可变（只注册不更新）。
        return True

    def summary(self) -> str:
        lines = []
        for uid, entry in self._archive.items():
            prefixes = [f"{r}: {p['prefix']}" for r, p in entry["role_prefixes"].items()]
            lines.append(f"  {uid} [{entry['industry']}] 前缀: {', '.join(prefixes)}")
        return "\n".join(lines) if lines else "  (空档案库)"

    def _save(self):
        with open(self.archive_file, "w", encoding="utf-8") as f:
            json.dump(self._archive, f, ensure_ascii=False, indent=2)
