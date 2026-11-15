"""M11 行业战略视图 · 大局观与战略视角（strategy_view）

## 一句话

**粒度红线：细到岗位（position）和角色（role）就停。** 再往下——工序、话术、
提示词、逐条职责、KPI——不写在这里，那是 AI 上到那个岗位、认清职责之后
自己充当角色时补的。这份账只回答一件事：**这个行业的钱为什么在这、AI 该站哪一段。**

为什么必须有这一层：41 个分区都有产值口径、六口径落点、生产法解释、资金流位置，
全是"多少钱"，没有一句"这钱为什么在这、拿什么去挣"。缺这一层的后果很具体——
AI 被派到「建筑工程-造价员」岗位上，它知道要算量，但不知道这个行业的利润不在算量
而在增项与材料差，于是它会认认真真把一个不赚钱的环节做到极致。

## 三条立场（沿用本仓库既有规矩）

1. **每个分区都要有落点。** 漏一个 = 这个行业只有数字没有判断，而覆盖率不会变红。
2. **粒度越界要报。** 出现 `steps`/`tasks`/`sop`/`prompt`/`kpi`/`persona` 这类字段即报：
   写死在这里的那一版职责，一定比市场慢半年，而且再没人回来改。
3. **战略落不到岗位就是口号。** `role_focus` 必须落在本分区真实存在的岗位或角色上
   （已建单元对 `unit-index` 的 roles，待建分区对 `planned_roles`）。

## 不抄数字

产值、就业、利润额、资产、估值一律不在这里重复存 —— 那是 `partition` 与六口径账
（`industry-scales.yaml`）的事。同一件事存两份，迟早对不上，而且没人知道哪份对。
所以本文件只有判断，没有金额。`validate` 会把 `cny`/`amount`/`gdp` 这类字段报出来。
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional

import yaml

from ._shape import add_all, dict_list

# 战略层的段。缺哪一段都要在 missing 里写原因 —— 说不出缺什么，等于保证它永远缺。
SECTIONS = ("value_chain", "position", "profit_pool", "leverage",
            "drivers", "risks", "ai_frontier", "division_of_labor", "role_focus")
# 粒度红线：这些字段名一旦出现，说明有人开始往下写到"怎么做"了。
# 不是洁癖：写死在数据里的工序，AI 上岗时会照着做而不是照着判断，而那一版永远过期。
GRANULARITY_VIOLATIONS = ("steps", "tasks", "sop", "prompt", "prompts", "kpi",
                          "kpis", "persona", "tool_calls", "workflow")
# 数字禁区：战略层只放判断，金额一律回 partition / 六口径账
AMOUNT_KEYS = ("cny", "amount", "amount_cny", "gdp", "gdp_cny", "revenue",
               "profit_cny", "value_cny", "employment")
# 价值链最短分段：少于 3 段谈不上"链"，只是把一件事换个说法
MIN_CHAIN = 3
# AI 承接面的三档，缺一档就说不清边界在哪
AI_FRONTIER_KEYS = ("strong", "weak", "boundary")


def _strs(raw) -> List[str]:
    """取字符串列表：单个字符串不拆成汉字，None 不变成 [None]。"""
    if not isinstance(raw, list):
        return []
    return [x for x in raw if isinstance(x, str) and x.strip()]


def _dicts(raw) -> List[dict]:
    """取映射列表：过滤掉混进来的标量（缺陷由 validate 报，这里只保证不崩）。"""
    if not isinstance(raw, list):
        return []
    return [x for x in raw if isinstance(x, dict)]


class StrategyView:
    """行业战略视图：价值链 → 利润池 → 杠杆 → 驱动/风险 → AI 承接面 → 岗位落点。"""

    def __init__(self, data_dir: Optional[str] = None,
                 partitions: Optional[List[dict]] = None,
                 registry=None):
        self.data_dir = data_dir or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "../../../data")
        self.path = os.path.join(self.data_dir, "industry-strategy.yaml")
        self.version = "0.1"
        self.updated_at = ""
        self.entries: Dict[str, dict] = {}
        # 文件在、内容是注释时 loaded 仍为 False —— 缺文件与空账分开报，都是硬失败
        self.loaded = False
        # 结构写歪（列表里混字符串、映射写成标量）记在这里，由 validate() 报。
        # `(it or {})` 只兜得住 None，兜不住字符串 —— 数据是手写的，
        # 列表里混一个字符串是最常见的写法之一，而它会让 `industry check` 崩。
        self.load_problems: List[str] = []
        # 形状写歪的段：`{分区: {段名}}`。validate() 末尾那条"空段要解释"
        # 要跳过它们 —— 已经报过"应写成映射"，再叠一条"缺这一段且没写原因"
        # 是把一条手滑说成两条，读的人会去补 missing 而不是去改结构。
        self._defect_sections: Dict[str, set] = {}
        self._partitions = partitions or []
        self._registry = registry
        self._load()

    # ---------------------------------------------------------------- load
    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        with open(self.path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        self.version = str(data.get("version", self.version))
        self.updated_at = str(data.get("updated_at", ""))
        where = os.path.basename(self.path)
        for row in dict_list(data.get("partitions"), "partitions",
                             self.load_problems, where):
            pid = row.get("partition") or ""
            if pid:
                self._check_sections(pid, row, where)
                self.entries[pid] = dict(row)
            else:
                self.load_problems.append(
                    f"{where} 的 partitions 里有一项没有 partition"
                    f"（这一段判断找不到归属的行业）")
        self.loaded = bool(self.entries)

    # 每一段该是什么形状：列表段里混进标量、映射段写成标量，都在入口记下来。
    # 不在消费点各兜一次 —— `(it or {})` 兜不住字符串，想到之外的路照样炸。
    _LIST_SECTIONS = ("value_chain", "profit_pool", "leverage", "drivers",
                      "risks", "role_focus")
    _MAP_SECTIONS = ("ai_frontier", "division_of_labor", "missing")

    def _check_sections(self, pid: str, row: dict, where: str) -> None:
        for name in self._LIST_SECTIONS:
            raw = row.get(name)
            if raw is None:
                continue
            if isinstance(raw, str):
                self.load_problems.append(
                    f"{where} 分区 {pid} 的 {name} 应写成列表，实际是一个字符串: "
                    f"{raw!r}（当成列表会把它逐字拆开，得到一串看着非空、"
                    f"其实没有意义的项）")
                row[name] = []
                self._defect_sections.setdefault(pid, set()).add(name)
            elif not isinstance(raw, list):
                self.load_problems.append(
                    f"{where} 分区 {pid} 的 {name} 应写成列表，实际是 "
                    f"{type(raw).__name__}: {raw!r}")
                row[name] = []
                self._defect_sections.setdefault(pid, set()).add(name)
            else:
                bad = [x for x in raw if not isinstance(x, dict)]
                if bad and name == "profit_pool":
                    self.load_problems.append(
                        f"{where} 分区 {pid} 的 {name} 里有 {len(bad)} 项不是映射"
                        f"（写成了 {type(bad[0]).__name__}）"
                        f"（当作不存在会让这一项静默消失，而它在报告里本该占一行）")
                    row[name] = [x for x in raw if isinstance(x, dict)]
                    self._defect_sections.setdefault(pid, set()).add(name)
        for name in self._MAP_SECTIONS:
            raw = row.get(name)
            if raw is not None and not isinstance(raw, dict):
                self.load_problems.append(
                    f"{where} 分区 {pid} 的 {name} 应写成映射，实际是 "
                    f"{type(raw).__name__}: {raw!r}"
                    f"（读不成映射会让整段内容消失，而「说不出」和「忘了写」"
                    f"在报告里长得一样）")
                # 归一：清成空映射，免得每个消费点各兜一次
                row[name] = {}
                self._defect_sections.setdefault(pid, set()).add(name)

    def bind(self, partitions: List[dict], registry=None) -> None:
        self._partitions = partitions
        if registry is not None:
            self._registry = registry

    # ------------------------------------------------------------- lookups
    def partition(self, pid: str) -> Optional[dict]:
        for p in self._partitions or []:
            if p.get("id") == pid:
                return p
        return None

    def entry(self, pid: str) -> Optional[dict]:
        return self.entries.get(pid)

    def missing_reason(self, pid: str, section: str) -> str:
        row = self.entries.get(pid) or {}
        miss = row.get("missing")
        if not isinstance(miss, dict):
            # 写歪了就当"没有原因"，但缺陷已由 validate() 报出——
            # 这里再把它说成"未填原因"等于把缺陷说成数据边界。
            return ""
        return str(miss.get(section, "") or "")

    def _roles_of(self, pid: str) -> List[str]:
        """本分区真实存在的岗位名：已建单元取注册表 roles，待建分区取 planned_roles。

        只认本分区。拿别处的同名岗位背书，等于允许凭空加一个"反正别处也在用"的名字。
        """
        p = self.partition(pid) or {}
        uid = p.get("unit_id") or ""
        if uid and self._registry is not None:
            unit = self._registry.get_unit(uid)
            if unit is not None:
                return [r.name for r in unit.roles]
        return list(p.get("planned_roles") or [])

    # ------------------------------------------------------------- 判断视图
    def row(self, pid: str) -> dict:
        """一个分区的战略视图（含缺段原因与岗位落点是否成立）。"""
        e = self.entries.get(pid) or {}
        roles = self._roles_of(pid)
        focus = _strs(e.get("role_focus"))
        # `_load` 已把形状归一（写歪的段清成空映射并记下 problem），
        # 这里不再 `or {}` 二次兜底 —— 兜两次的结果是同一份数据两种结论：
        # validate 说「应写成映射」，row() 却 traceback。
        frontier = e.get("ai_frontier") if isinstance(e.get("ai_frontier"), dict) else {}
        return {
            "partition": pid,
            "value_chain": _strs(e.get("value_chain")),
            "position": e.get("position", "") or "",
            "profit_pool": _dicts(e.get("profit_pool")),
            "leverage": _dicts(e.get("leverage")),
            "drivers": _strs(e.get("drivers")),
            "risks": _strs(e.get("risks")),
            "ai_strong": _strs(frontier.get("strong")),
            "ai_weak": _strs(frontier.get("weak")),
            "ai_boundary": frontier.get("boundary", "") or "",
            "human_decides": _strs((e.get("division_of_labor") or {})
                                   .get("human_decides")),
            "ai_fills": _strs((e.get("division_of_labor") or {}).get("ai_fills")),
            "role_focus": focus,
            "role_focus_valid": [r for r in focus if r in roles],
            "role_focus_dangling": [r for r in focus if r not in roles],
            "missing": {k: v for k, v in
                        (e.get("missing") if isinstance(e.get("missing"), dict) else {})
                        .items() if v},
            "sections": [s for s in SECTIONS if e.get(s)],
        }

    def rows(self) -> List[dict]:
        return [self.row(p.get("id", "")) for p in self._partitions or []
                if p.get("id")]

    def summary(self) -> dict:
        rows = self.rows()
        covered = [r for r in rows if r["partition"] in self.entries]
        with_focus = [r for r in covered if r["role_focus_valid"]]
        return {
            "loaded": bool(self.loaded),
            "partitions": len(rows),
            "covered": len(covered),
            "with_role_focus": len(with_focus),
            "dangling_focus": sum(len(r["role_focus_dangling"]) for r in covered),
            "missing_sections": sum(len(r["missing"]) for r in covered),
        }

    # ------------------------------------------------------------- 贯穿判断
    def cross_view(self, db) -> List[dict]:
        """把战略结论和已有的钱对上：利润池落在哪几段、AI 承接面和供给结构是否打架。

        这里有价值的一条：分区的 `provider_mix` 说「AI 占 X%」，战略层说
        「哪几段 AI 站得住」。两者长期不一致，说明要么供给结构填估了，要么
        战略判断是拍脑袋 —— 两个都由人写，只有并排放才看得出矛盾。
        """
        rows: List[dict] = []
        for r in self.rows():
            pid = r["partition"]
            p = db.partition(pid) or {}
            members = db.members_of(pid)
            mix = db.provider_distribution(members) if members else {}
            strong = len(r["ai_strong"])
            weak = len(r["ai_weak"])
            rows.append({
                "partition": pid,
                "name": p.get("name", ""),
                "status": p.get("status", ""),
                "chain_len": len(r["value_chain"]),
                "pools": len(r["profit_pool"]),
                "ai_strong": strong,
                "ai_weak": weak,
                "ai_share_measured": mix.get("ai") if members else None,
                "role_focus": len(r["role_focus_valid"]),
                "dangling": r["role_focus_dangling"],
                "missing": r["missing"],
            })
        return rows

    # ------------------------------------------------------------ validate
    def validate(self) -> List[str]:
        """战略视图自检。每条都对应一种"只有数字、没有判断"的失效方式。"""
        problems: List[str] = add_all([], self.load_problems)
        if not os.path.exists(self.path):
            problems.append(
                f"未读到行业战略视图: {self.path}（数据源缺失，自检不能视为通过）")
        elif not self.loaded:
            problems.append(
                f"行业战略视图是空账: {self.path}"
                f"（文件在但没有任何分区——空账验不出任何判断）")

        known = {p.get("id") for p in (self._partitions or []) if p.get("id")}

        # 1. 落点：每个分区都要有战略视图，悬空条目也要报
        for pid in self.entries:
            if known and pid not in known:
                problems.append(
                    f"战略视图里的分区 {pid} 不是已知分区（悬空条目，永远查不到）")
        for pid in known:
            if pid not in self.entries:
                problems.append(
                    f"分区 {pid} 没有行业战略视图"
                    f"（这个行业只有数字、没有判断——钱为什么在这、AI 该站哪一段，"
                    f"没人写过）")

        for pid, e in self.entries.items():
            # 2. 粒度红线：写到"怎么做"就是越界
            for key in self._walk_keys(e):
                low = key.lower()
                if low in GRANULARITY_VIOLATIONS:
                    problems.append(
                        f"分区 {pid} 的战略视图出现字段 {key!r}"
                        f"（粒度只到岗位/角色；工序/话术/KPI 由 AI 上岗后按职责补，"
                        f"写死在这里的那版一定比市场慢半年）")
                if low in AMOUNT_KEYS:
                    problems.append(
                        f"分区 {pid} 的战略视图出现金额字段 {key!r}"
                        f"（战略层只放判断，金额回 partition / 六口径账，别存第二份）")

            # 3. 价值链：少于 3 段谈不上链
            chain = _strs(e.get("value_chain"))
            if len(chain) < MIN_CHAIN:
                if not self.missing_reason(pid, "value_chain"):
                    problems.append(
                        f"分区 {pid} 的 value_chain 只有 {len(chain)} 段"
                        f"（少于 {MIN_CHAIN} 段谈不上价值链：说不出缺什么就写 missing）")

            # 4. 利润池：每项都要有 where + why，且 where 落在价值链里
            pools = e.get("profit_pool") or []
            if not _dicts(pools):
                if not self.missing_reason(pid, "profit_pool"):
                    problems.append(
                        f"分区 {pid} 没有利润池判断，也没写为什么"
                        f"（钱沉在哪几段是这层最要紧的一句）")
            stages = {str(x) for x in chain}
            # 混进字符串的项已在 _load 记了 problem，这里跳过它继续查其余项——
            # 一条手滑不该让后面所有利润池判断都失去检查。
            for it in _dicts(pools):
                where = (it or {}).get("where") or ""
                why = (it or {}).get("why") or ""
                if not where or not why:
                    problems.append(
                        f"分区 {pid} 的利润池有一条缺 where 或 why（{it}）")
                elif stages and where not in stages:
                    problems.append(
                        f"分区 {pid} 的利润池指向 {where!r}，不在它的价值链 "
                        f"{sorted(stages)} 里（说钱沉在一个链条上不存在的环节）")

            # 5. AI 承接面：三档齐，缺一档就说不清边界
            frontier = e.get("ai_frontier") if isinstance(e.get("ai_frontier"), dict) else {}
            for key in AI_FRONTIER_KEYS:
                if frontier and not frontier.get(key):
                    problems.append(
                        f"分区 {pid} 的 ai_frontier 缺 {key}"
                        f"（强/弱/边界三档缺一档，就说不清 AI 该停在哪）")

            # 6. 分工：人管什么、AI 补什么，两边都要有
            dol = e.get("division_of_labor") if isinstance(
                e.get("division_of_labor"), dict) else {}
            for key in ("human_decides", "ai_fills"):
                if dol and not dol.get(key):
                    problems.append(
                        f"分区 {pid} 的 division_of_labor 缺 {key}"
                        f"（只写一边等于把另一边默认成谁都行）")

            # 7. 岗位落点：战略落不到真实岗位 = 一句没人负责的口号
            focus = _strs(e.get("role_focus"))
            if not focus:
                if not self.missing_reason(pid, "role_focus"):
                    problems.append(
                        f"分区 {pid} 没有 role_focus，也没写为什么"
                        f"（战略结论不落到岗位，等于一句口号）")
                continue
            roles = self._roles_of(pid)
            if roles:
                for name in focus:
                    if name not in roles:
                        problems.append(
                            f"分区 {pid} 的 role_focus 指向不存在的岗位 {name!r}"
                            f"（本分区岗位: {roles}）")
            # 8. 空段要解释：说不出缺什么，等于保证它永远缺
            for section in SECTIONS:
                if e.get(section):
                    continue
                if section in self._defect_sections.get(pid, ()):
                    # 形状写歪已单独报过，不再叠一条"缺段没写原因"：
                    # 一条手滑报两条，读的人会去补 missing 而不是改结构。
                    continue
                if not self.missing_reason(pid, section):
                    problems.append(
                        f"分区 {pid} 缺 {section} 段且没写 missing 原因"
                        f"（说不出这一行为什么空，等于保证它一直是空的）")
        return problems

    @staticmethod
    def _walk_keys(obj, depth: int = 0) -> List[str]:
        """把嵌套结构里的键名摊平，用来查粒度越界与金额字段。"""
        keys: List[str] = []
        if depth > 6:
            return keys
        if isinstance(obj, dict):
            for k, v in obj.items():
                keys.append(str(k))
                keys.extend(StrategyView._walk_keys(v, depth + 1))
        elif isinstance(obj, list):
            for v in obj:
                keys.extend(StrategyView._walk_keys(v, depth + 1))
        return keys
