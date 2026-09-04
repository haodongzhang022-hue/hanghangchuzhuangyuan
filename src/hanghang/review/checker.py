"""代码规范检查器（Standard Checker）

参考自 dongjiagoushi / youxikaifaxilieagent 的 dev-standard 检查机制。
在 PR/代码提交时自动检查代码规范，硬失败则阻断合并。
"""
from __future__ import annotations

import os
import re
from typing import Dict, List, Tuple


class StandardChecker:
    """
    轻量代码规范检查器：对 Python 源码做静态检查。
    规则：
    - 硬失败（hard）→ 阻断流水线
    - 警告（warning）→ 不阻断但提示
    """

    # 真正的待办标记：带冒号或括号（如 "待办: xxx"）
    TODO_PATTERN = re.compile(r"\b(?:TODO|FIXME)\s*[:(]")

    # 硬失败规则
    HARD_RULES = {
        # 裸 except
        "bare_except": re.compile(r"^\s*except\s*:\s*(?:pass\s*)?$"),
        # star import
        "star_import": re.compile(r"^\s*from\s+[\w.]+\s+import\s+\*"),
    }

    # 警告规则
    WARN_RULES = {
        # 行过长
        "line_too_long": re.compile(r"^.{121,}$"),
    }

    def __init__(self, root_dir: str | None = None):
        self.root_dir = root_dir or os.getcwd()

    def check_file(self, filepath: str) -> Tuple[bool, List[Dict]]:
        """检查单个 Python 文件，返回 (是否通过, 问题列表)"""
        issues = []
        if not filepath.endswith(".py"):
            return True, issues

        full_path = filepath
        if not os.path.isabs(full_path):
            full_path = os.path.join(self.root_dir, filepath)

        if not os.path.exists(full_path):
            return True, issues

        if "__pycache__" in full_path:
            return True, issues

        with open(full_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # 是否为 CLI 文件（print 是合法输出）或库代码
        is_cli = "/cli/" in full_path or "cli/" in full_path
        is_in_src = "src/" in full_path

        for i, line in enumerate(lines, 1):
            content = line.rstrip("\n")
            stripped = content.lstrip()
            is_comment = stripped.startswith("#")

            # --- 硬失败检查 ---

            # 1. TODO/FIXME 标记（在注释中也是问题）
            #    排除自身描述 TODO 规则的文字（在注释中以反引号包裹的 TODO 不算）
            if self.TODO_PATTERN.search(content) and "noqa" not in content:
                # 跳过那些描述性的 "TODO/FIXME 注释检查" 文本中
                # 关键词后没有冒号/括号的内容，即不是真正的标记
                # TODO_PATTERN 已要求 TODO 后跟 : 或 (
                issues.append({
                    "severity": "hard",
                    "file": filepath,
                    "line": i,
                    "rule": "todo_comment",
                    "message": f"发现未清理的 TODO/FIXME 标记: {content.strip()[:80]}",
                })

            # 2. 裸 except / star import
            for rule_name, pattern in self.HARD_RULES.items():
                if is_comment:
                    continue
                if "noqa" in content:
                    continue
                if pattern.search(content):
                    issues.append({
                        "severity": "hard",
                        "file": filepath,
                        "line": i,
                        "rule": rule_name,
                        "message": f"违反规范 {rule_name}: {content.strip()[:80]}",
                    })

            # 3. src/ 库代码中的裸 print（CLI 文件允许）
            if is_in_src and not is_cli and not is_comment and "noqa" not in content:
                if re.match(r"^\s*print\(", content):
                    issues.append({
                        "severity": "hard",
                        "file": filepath,
                        "line": i,
                        "rule": "debug_print",
                        "message": f"库代码中不应有 print: {content.strip()[:80]}",
                    })

            # --- 警告检查 ---
            if not is_comment and len(content) > 120:
                issues.append({
                    "severity": "warning",
                    "file": filepath,
                    "line": i,
                    "rule": "line_too_long",
                    "message": f"行过长({len(content)}字符 > 120)",
                })

        # 判断是否通过
        hard_issues = [i for i in issues if i["severity"] == "hard"]
        return len(hard_issues) == 0, issues

    def check_dir(self, dirpath: str | None = None) -> Tuple[bool, List[Dict]]:
        """检查目录下所有 Python 文件"""
        dirpath = dirpath or os.path.join(self.root_dir, "src")
        all_issues = []
        all_pass = True

        if not os.path.exists(dirpath):
            return all_pass, all_issues

        for root, dirs, files in os.walk(dirpath):
            if "__pycache__" in root or ".git" in root:
                continue
            for f in files:
                if f.endswith(".py"):
                    rel_path = os.path.relpath(os.path.join(root, f), self.root_dir)
                    ok, issues = self.check_file(rel_path)
                    if not ok:
                        all_pass = False
                    all_issues.extend(issues)

        return all_pass, all_issues

    def summary(self) -> str:
        """运行检查并返回摘要"""
        passed, issues = self.check_dir()
        hard = [i for i in issues if i["severity"] == "hard"]
        warnings = [i for i in issues if i["severity"] == "warning"]

        lines = [f"代码规范检查: {'✅ 通过' if passed else '❌ 存在硬失败'}"]
        lines.append(f"  硬失败: {len(hard)} 条")
        lines.append(f"  警告: {len(warnings)} 条")

        for issue in issues[:10]:
            lines.append(f"  [{issue['severity']}] {issue['file']}:{issue['line']} - {issue['message']}")
        if len(issues) > 10:
            lines.append(f"  ... 还有 {len(issues) - 10} 条")

        return "\n".join(lines)
