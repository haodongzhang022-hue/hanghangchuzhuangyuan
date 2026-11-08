"""全球分类框架 · global-framework

设计立场：**世界上没有"一套全的分类"，只有四根互不正交的轴。**

- 职业轴（occupation）：这个人在干什么活。锚点：中国大典 2022 / ISCO-08 / SOC / O*NET。
- 行业轴（industry）：这家单位在卖什么。锚点：GB/T 4754 / ISIC / NACE / NAICS。
- 税收轴（tax）：这笔钱按什么税目征。**税率跟"卖的是什么"走，不跟行业走**，
  所以必须单独成轴 —— 塞进分区表，一次税率调整就污染整张聚类表。
- 产出轴（output）：一年多大产值、多少人。锚点：统计局增加值 / ILOSTAT。

本模块只做两件事：读 ISCO-08 只读参考表、读 classification-sources.yaml 索引。
不落盘、不写映射、不参与 coverage 分母 —— 外部全集（436 / 1636 / 1380）永远
是"还能挑多少"，不是"还欠多少"。

为什么要这张 ISCO 表：中国大典是本国口径，跨境对齐、海外招聘、国际统计比对
都接不上。ISCO-08 是各国职业分类的公共母版（SOC/ANZSCO/NOC/KldB/中国大典
都按它对标），有了这层锚点，"某个职业在别国叫什么、归哪一类"才有得查。
"""
from __future__ import annotations

import logging
import os
import re
from typing import Dict, List, Optional

import yaml

ISCO_FILE = "occupation-catalog-isco08.yaml"
SOURCES_FILE = "classification-sources.yaml"

# 编码位数 = 层级。短码是长码前缀，所以按长度分就够了，不用额外字段。
LEVELS = {1: "major_groups", 2: "sub_major_groups",
          3: "minor_groups", 4: "unit_groups"}
LEVEL_NAMES = {1: "大类", 2: "次大类", 3: "小类", 4: "细类"}

# 四根轴的名字，和 classification-sources.yaml 的 axes 段对应
AXES = ("occupation", "industry", "tax", "output")


class IscoCatalog:
    """ISCO-08 只读参考表。缺文件时降级为空表，不抛异常拖垮调用方。"""

    def __init__(self, ref_dir: Optional[str] = None):
        self.ref_dir = ref_dir or _find_data_dir()
        self.path = os.path.join(self.ref_dir, ISCO_FILE)
        self.version = ""
        self.stats: Dict[str, int] = {}
        self.by_level: Dict[int, List[dict]] = {k: [] for k in LEVELS}
        self._by_code: Dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.path):
            logging.warning(f"缺少 ISCO-08 参考表: {self.path}")
            return
        with open(self.path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        self.version = data.get("version", "") or ""
        self.stats = data.get("stats", {}) or {}
        for lvl, key in LEVELS.items():
            self.by_level[lvl] = data.get(key, []) or []
        self._by_code = {r["code"]: r for rows in self.by_level.values()
                         for r in rows if r.get("code")}

    # ------------------------------------------------------------- queries
    def entry(self, code: str) -> Optional[dict]:
        return self._by_code.get(str(code))

    def level_of(self, code: str) -> int:
        """编码 → 层级(1-4)。空码/超长返回 0。"""
        n = len(str(code or ""))
        return n if n in LEVELS else 0

    def path_of(self, code: str) -> str:
        """编码 → "Managers / ... / Software developers" 的英文归属链路。"""
        code = str(code or "")
        names = []
        for i in range(1, len(code) + 1):
            e = self.entry(code[:i])
            if e:
                names.append(e.get("name", ""))
        return " / ".join(names)

    def children_of(self, code: str) -> List[dict]:
        """下一层直接子节点。细类(4 位)没有子节点。"""
        code = str(code or "")
        want = len(code) + 1
        if want not in LEVELS:
            return []
        return [r for r in self.by_level[want]
                if str(r.get("code", "")).startswith(code)]

    def search(self, keyword: str, limit: int = 20) -> List[dict]:
        """按名称或示例职位名搜。示例名比正式名更像人话，一起搜才查得动。"""
        kw = (keyword or "").strip().lower()
        if not kw:
            return []
        hits = []
        for r in self._by_code.values():
            hay = [r.get("name", "")] + list(r.get("examples") or [])
            if any(kw in str(x).lower() for x in hay):
                hits.append(r)
        hits.sort(key=lambda r: (len(r.get("code", "")), r.get("code", "")))
        return hits[:limit] if limit else hits

    def occupations(self, unit_only: bool = True) -> List[dict]:
        rows = self.by_level[4] if unit_only else [
            r for rows in self.by_level.values() for r in rows]
        return sorted(rows, key=lambda r: r.get("code", ""))

    def example_count(self) -> int:
        return sum(len(r.get("examples") or []) for r in self.by_level[4])

    # ------------------------------------------------------------ validate
    def validate(self) -> List[str]:
        """ISCO 表自检：层级齐全、编码位数正确、子码前缀连续。

        这几条错了不会让任何统计变红，只会让"按码查归属"静默返回半截路径。
        """
        problems: List[str] = []
        if not self._by_code:
            problems.append(
                f"ISCO-08 参考表未加载或为空: {self.path}（跨境对齐能力缺失，"
                f"不能当作'没有 ISCO 映射所以没问题'）")
            return problems

        for lvl, key in LEVELS.items():
            rows = self.by_level[lvl]
            if not rows:
                problems.append(f"ISCO-08 {LEVEL_NAMES[lvl]}({key}) 为空")
                continue
            declared = self.stats.get(key)
            if declared is not None and int(declared) != len(rows):
                problems.append(
                    f"ISCO-08 {key} 声明 {declared} 条，实际 {len(rows)} 条"
                    f"（stats 与实际不符，看板数字会骗人）")
            for r in rows:
                code = str(r.get("code", ""))
                if len(code) != lvl:
                    problems.append(
                        f"ISCO-08 编码 {code!r} 位数 {len(code)} 与所在层 "
                        f"{LEVEL_NAMES[lvl]}({lvl} 位) 不符")
                if lvl > 1 and code[:-1] not in self._by_code:
                    problems.append(
                        f"ISCO-08 编码 {code} 的上级 {code[:-1]} 不存在"
                        f"（按码查归属会断在半路）")
        return problems


class ClassificationSources:
    """分类体系索引：哪套表管哪根轴、已接入还是待接、规模多少。"""

    def __init__(self, ref_dir: Optional[str] = None):
        self.ref_dir = ref_dir or _find_data_dir()
        self.path = os.path.join(self.ref_dir, SOURCES_FILE)
        self.axes: Dict[str, dict] = {}
        self.sources: List[dict] = []
        self.rules: List[dict] = []
        self.updated_at = ""
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.path):
            logging.warning(f"缺少分类体系索引: {self.path}")
            return
        with open(self.path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        self.axes = data.get("axes", {}) or {}
        self.sources = data.get("sources", []) or []
        self.rules = data.get("rules", []) or []
        self.updated_at = data.get("updated_at", "") or ""

    def by_axis(self, axis: str = "") -> List[dict]:
        if not axis:
            return list(self.sources)
        return [s for s in self.sources if s.get("axis") == axis]

    def by_status(self, status: str = "") -> List[dict]:
        if not status:
            return list(self.sources)
        return [s for s in self.sources if s.get("status") == status]

    def get(self, sid: str) -> Optional[dict]:
        for s in self.sources:
            if s.get("id") == sid:
                return s
        return None

    def validate(self) -> List[str]:
        """索引自检：axis/status 必须是已知枚举，id 唯一，integrated 必须给 we_have。"""
        problems: List[str] = []
        if not self.sources:
            problems.append(f"分类体系索引为空: {self.path}")
            return problems
        if self.axes and set(self.axes) - set(AXES):
            problems.append(
                f"分类体系索引出现未知轴 {sorted(set(self.axes) - set(AXES))}")
        valid_status = ("integrated", "to-add", "candidate")
        seen = set()
        for s in self.sources:
            sid = s.get("id") or ""
            if not sid:
                problems.append("分类体系索引有条目缺 id")
                continue
            if sid in seen:
                problems.append(f"分类体系索引 id 重复: {sid}")
            seen.add(sid)
            if s.get("axis") not in AXES:
                problems.append(
                    f"{sid} 的 axis={s.get('axis')!r} 不在 {list(AXES)} 中"
                    f"（轴写错等于消失在框架外）")
            if s.get("status") not in valid_status:
                problems.append(
                    f"{sid} 的 status={s.get('status')!r} 不在 {list(valid_status)} 中")
            if s.get("status") == "integrated" and not s.get("we_have"):
                problems.append(f"{sid} 标记 integrated 但没写 we_have 落地路径")
        return problems

    def render_text(self, axis: str = "") -> str:
        rows = self.by_axis(axis)
        if not rows:
            return f"没有匹配的分类体系（axis={axis or '全部'}）"
        tag = {"integrated": "已接入", "to-add": "待接入", "candidate": "候选"}
        lines = [f"分类体系索引（{len(rows)} 套）"
                 + (f" · 轴={axis}" if axis else "")]
        for s in rows:
            scale = s.get("scale") or {}
            sz = " / ".join(f"{k} {v}" for k, v in scale.items())
            lines.append(f"■ {s.get('id')}  [{tag.get(s.get('status'), s.get('status'))}]"
                         f" 轴={s.get('axis')}")
            lines.append(f"  {s.get('name')}")
            lines.append(f"  维护: {s.get('maintainer')} · {s.get('version')}"
                         + (f" · {sz}" if sz else ""))
            if s.get("we_have"):
                lines.append(f"  落地: {s['we_have']}")
        if not axis:
            lines.append("")
            lines.append("四根轴："
                         + " / ".join(f"{k}={v.get('question', '')}"
                                      for k, v in self.axes.items()))
        return "\n".join(lines)


def _find_data_dir() -> str:
    """返回 data/reference 目录（与 industry_db 同一套定位方式）。"""
    cands = [os.path.join(os.getcwd(), "data", "reference"),
             os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "../../data/reference")]
    for c in cands:
        if os.path.isdir(c):
            return os.path.abspath(c)
    return os.path.abspath(cands[0])
