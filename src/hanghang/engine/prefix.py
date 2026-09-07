"""M3 稳定前缀档案库"""
from __future__ import annotations

import json
import os
import tempfile
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

        幂等说明：persist=True 时 `_save` 采用"内容漂移才落盘"策略——
        仅在内存内容与磁盘现有内容不一致时触发一次文件写入；无差异则不写，
        从而对 git 跟踪的 data/prefix-archive.json 保持干净，也不覆盖人工维护的改动。
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
        """幂等持久化：仅当内容漂移（与磁盘现有内容不一致）时才落盘。

        被 git 跟踪的 data/prefix-archive.json 在服务/CLI 每次启动时都会走
        register_unit(persist=True)。若不比对即重写，即使数据未变化也会触碰
        文件（mtime 变化、覆盖潜在人工改动）。这里序列化当前内存档案并与磁盘
        现有字节比对，无差异则直接返回，真正做到 git status 干净且幂等。
        """
        payload = json.dumps(self._archive, ensure_ascii=False, indent=2)
        try:
            with open(self.archive_file, "r", encoding="utf-8") as f:
                existing = f.read()
        except (OSError, IOError):
            existing = None
        if existing == payload:
            return  # 无漂移，无需重写

        # 原子落盘：同目录临时文件 + os.replace 原子替换。
        # 临时文件与被替换文件同目录 → 同文件系统内 rename 是原子的，
        # 读方永远只看到"完整旧内容"或"完整新内容"，消除并发写导致的
        # 半写/截断/丢失更新中间态被读到的问题。
        dirname = os.path.dirname(self.archive_file) or "."
        fd, tmp_path = tempfile.mkstemp(
            prefix=".prefix-archive-", suffix=".tmp", dir=dirname)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())  # 确保数据真正落盘后再替换
            os.replace(tmp_path, self.archive_file)
        except BaseException:
            # 任一环节失败：清理临时文件，目标文件保持原状，异常向上抛出
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
