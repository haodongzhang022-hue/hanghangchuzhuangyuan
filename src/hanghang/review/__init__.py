"""评审处置模块：统一审查处置标签 + 自动化检查器"""
from .disposition import Disposition, ReviewResult, dispose, parse_disposition
from .checker import StandardChecker

__all__ = [
    "Disposition", "ReviewResult", "dispose", "parse_disposition",
    "StandardChecker",
]
