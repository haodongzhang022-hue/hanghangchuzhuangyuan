"""M11 投入产出账 · 中间投入与去重（input_output）

## 一句话

上一轮资金流账卡在同一句话上：「8 个行业池的份额切分数额全待补，卡点不是拿不到
数，是拿了会重复计」。这份账就是那个卡点的答案 —— **生产法恒等式**：

    总产出 = 增加值 + 中间投入

三个数来自三个独立来源：总产出看行业统计（总产值/营业收入/GMV），增加值看国民
经济核算，中间投入由投入产出表或两者相减。两边对不上，说明其中一个是别的口径。

## 为什么"营业收入不能直接当增加值切分"

电商 15 万亿是 GMV（平台两头各计价一次），软件研发 6 万亿是软件业务收入（含硬件
与中间投入），建筑业 31.6 万亿是总产值（含分包重复报量）。部门层的总额是**增加值
性质**（收入法 GDP），拿收入去切部门总额，切出来的份额必然虚高 —— 而且虚高得看
不出来（每个数都抄对了）。

所以切分锚点只有两条合法路径：
  1. 分区本来就是 `value_added` 口径 → 直接可切
  2. 分区是 output/revenue/GMV → 必须先有 `va_ratio`（增加值 ÷ 总产出），
     折算成增加值再切。**没有 va_ratio 就不许切**，宁可留 null。

## 三处不得重复计（validate 里逐条守）

  a. 中间投入构成合计 = 中间投入总额（声明 `complete` 时）
     —— 同一件事存两份，迟早一边改了另一边没改，而没人知道哪份是对的。
  b. 某分区作为供给方出现在别人的 `inputs` 里，合计 ≤ 它自己的总产出
     —— 供不出比自己产出更多的东西。这是"去重"的关门条件。
  c. 所有分区增加值合计 ≤ 全国 GDP
     —— 超了必然是同一笔价值被两个分区各算了一遍（跨分区重复归属）。

## 数值立场

只有**能推出**的才填：建筑业总产出与增加值都在官方基准里，中间投入由恒等式相减得出
（标 `derived: true`）。其余分区宁可在 `missing` 里写清缺哪一端，也不按比例切一份
—— 按比例切出来的数，后面所有人都会当实测用。
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional

import yaml

from ._shape import add_all, as_mapping, dict_list, nested_list

# 三端。缺哪一端，决定了这一行"能不能切分"和"能不能验"。
TERMS = ("output", "value_added", "intermediate")
# 切分锚点：value_added 直接可切 / va_ratio 折一半 / none 不可切
ANCHORS = ("value_added", "va_ratio", "none")
DEFAULT_TOLERANCE = 0.03


class InputOutputBook:
    """投入产出账：生产法三端 + 中间投入构成 + 行业池切分可行性。"""

    def __init__(self, data_dir: Optional[str] = None,
                 partitions: Optional[List[dict]] = None):
        self.data_dir = data_dir or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "../../../data")
        self.path = os.path.join(self.data_dir, "industry-input-output.yaml")
        self.version = "0.1"
        self.updated_at = ""
        self.year: Optional[int] = None
        self.tolerance = DEFAULT_TOLERANCE
        self.accounts: Dict[str, dict] = {}
        self.pool_rules: List[dict] = []
        # 文件在、内容是注释时 exists() 照样 True —— 缺文件与空账分开报，都是硬失败
        self.loaded = False
        # 结构写歪记这里，由 validate() 报（不在每个消费点各兜一次：
        # `(it or {})` 兜不住字符串，而列表里混字符串是最常见的写法之一）
        self.load_problems: List[str] = []
        self._partitions = partitions or []
        self._load()

    # ---------------------------------------------------------------- load
    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        with open(self.path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        self.version = str(data.get("version", self.version))
        self.updated_at = str(data.get("updated_at", ""))
        y = data.get("year")
        self.year = int(y) if isinstance(y, int) and not isinstance(y, bool) else None
        tol = data.get("tolerance")
        if isinstance(tol, (int, float)) and not isinstance(tol, bool) and tol > 0:
            self.tolerance = float(tol)
        where = os.path.basename(self.path)
        for row in dict_list(data.get("accounts"), "accounts",
                             self.load_problems, where):
            pid = row.get("partition") or ""
            if pid:
                self._normalize_account(pid, row, where)
                self.accounts[pid] = dict(row)
            else:
                self.load_problems.append(
                    f"{where} 的 accounts 里有一项没有 partition"
                    f"（这个生产法账户找不到归属行业）")
        self.pool_rules = dict_list(data.get("pool_rules"), "pool_rules",
                                    self.load_problems, where)
        self.loaded = bool(self.accounts)

    def bind(self, partitions: List[dict]) -> None:
        self._partitions = partitions

    # 三端金额段：写歪了要报，而不是让每个消费点各兜一次
    _TERM_SECTIONS = ("output", "value_added", "intermediate")

    def _normalize_account(self, pid: str, row: dict, where: str) -> None:
        """账户里嵌套段的形状归一：三段金额是映射，inputs 是对象列表。

        收口只收顶层等于没收：`(acc.get("intermediate") or {}).get("derived")`
        在 intermediate 写成标量时，`or {}` 短路不生效（标量是真值），
        `.get` 直接打在 int 上 —— 而 `term()` 对同一字段有 isinstance 保护，
        于是同一份数据两种结局：金额读成 None，derived 那行崩。
        """
        for name in self._TERM_SECTIONS:
            raw = row.get(name)
            if raw is None:
                continue
            if isinstance(raw, dict):
                continue
            # 写歪：清成 {} 以免下面每个消费点还要各兜一次。
            # 缺陷**必须**记进 load_problems —— 静默清空等于把"写坏了"说成"没有这一项"，
            # 而那正是这轮在拆的那种错。
            row[name] = as_mapping(raw, name, self.load_problems, where,
                                   label=f"分区 {pid} 的 {name}")
        row["inputs"] = nested_list(row, "inputs", f"分区 {pid} 的 inputs",
                                    self.load_problems, "")

    # ------------------------------------------------------------- lookups
    def partition(self, pid: str) -> Optional[dict]:
        for p in self._partitions or []:
            if p.get("id") == pid:
                return p
        return None

    @staticmethod
    def term(acc: dict, name: str) -> Optional[float]:
        """某一端的金额。缺失/非数值一律 None，不当 0。"""
        cell = (acc or {}).get(name)
        if not isinstance(cell, dict):
            return None
        v = cell.get("cny")
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
        return float(v)

    def va_ratio(self, pid: str) -> Optional[float]:
        """增加值率 = 增加值 ÷ 总产出。声明值优先，否则两端都有时现算。

        刻意不做"用行业平均值兜底"：平均增加值率套到一个具体行业上，
        得到的是一个看起来合理的错数 —— 比留空危险得多。
        """
        acc = self.accounts.get(pid) or {}
        declared = acc.get("va_ratio")
        if isinstance(declared, (int, float)) and not isinstance(declared, bool):
            return float(declared)
        out = self.term(acc, "output")
        va = self.term(acc, "value_added")
        if out and out > 0 and va is not None:
            return va / out
        return None

    def missing_reason(self, pid: str, name: str) -> str:
        acc = self.accounts.get(pid) or {}
        miss = acc.get("missing") or {}
        return str(miss.get(name, "") or "")

    # ------------------------------------------------------------- 恒等式
    def identity(self, pid: str) -> dict:
        """生产法恒等式校验：总产出 = 增加值 + 中间投入。

        结论只有六种，别用空字符串当"没问题"（那与"没验过"分不清）：
          ok          两端都在且闭合（或中间投入由相减得出）
          gap         两端都在但对不上（超容差）
          zero_rhs    增加值+中间投入 = 0，而总产出非 0（数据错，不是口径差）
          zero_output 总产出 = 0，而两端合计非 0（数据错，不是口径差）
          partial     只够一端，验不了 —— 但缺的那端要写清为什么
          missing     两端都没有（该分区在这张账里还没有落点）

        两个 zero_* 单列而不并进 gap：gap 的语义是"两个都对但口径不同"，
        除以 0 得到的偏差既不是 0 也不是超容差，混进去只会让下游拿 None 去格式化。
        """
        acc = self.accounts.get(pid) or {}
        out = self.term(acc, "output")
        va = self.term(acc, "value_added")
        mid = self.term(acc, "intermediate")
        derived = bool((acc.get("intermediate") or {}).get("derived"))
        row = {"partition": pid, "output": out, "value_added": va,
               "intermediate": mid, "derived": derived,
               "va_ratio": self.va_ratio(pid), "tolerance": self.tolerance,
               "status": "", "deviation": None}
        if out is None and va is None:
            row["status"] = "missing"
            return row
        if out is None or va is None:
            row["status"] = "partial"
            return row
        if mid is None:
            # 中间投入缺失：要么该补投入产出表，要么本来就该由相减得出（没标 derived
            # 就是不想要这个数，不替它算）。
            row["status"] = "partial"
            return row
        # 三段都在：比两侧合计。相减得出的中间投入天然闭合，所以偏差为 0 ——
        # 但 derived 行仍要算一遍：它同时是"总产出与增加值同源同口径"的交叉验证。
        rhs = va + mid
        if not rhs:
            # 报了增加值/中间投入却说两端合计为 0，本身就是数据错（0 是实测值不是缺失，
            # 所以能过 validate 第 1 条）。这里不能留下 deviation=None 走 gap 分支：
            # 下游 `abs(dev)` 与 `f"{deviation:+.1%}"` 都会 TypeError，
            # 结果校验器自己崩掉——红灯既不是"数据坏了"也不是绿。
            row["status"] = "zero_rhs"
            return row
        if not out:
            # 总产出 0 而两端合计非 0：同样是数据错。单列一档，
            # 免得 (out - rhs) / out 除零得到 None 后再 abs(None)。
            row["status"] = "zero_output"
            row["deviation"] = None
            return row
        dev = (out - rhs) / out
        row["deviation"] = dev
        row["status"] = "ok" if abs(dev) <= self.tolerance else "gap"
        return row

    # -------------------------------------------------------- 池切分可行性
    def pool_feasibility(self) -> List[dict]:
        """行业池能不能切、按什么锚切。这是上轮"份额切分待补"的直接答案。

        允许切的前提是拿到**增加值口径**的锚点（或能折算成增加值的 va_ratio）。
        拿 GMV/成本总额/营业收入去切部门总额，切出来的份额是虚的，而且虚得看不出来。
        """
        rows: List[dict] = []
        rules = {r.get("partition"): r for r in self.pool_rules}
        seen = set()
        for pid, rule in rules.items():
            seen.add(pid)
            anchor = rule.get("anchor") or ""
            acc = self.accounts.get(pid) or {}
            va = self.term(acc, "value_added")
            ratio = self.va_ratio(pid)
            note = rule.get("note", "")
            if anchor == "value_added" and va:
                status, anchor_value = "ready", va
            elif anchor == "va_ratio" and va and ratio:
                status, anchor_value = "ready", va
            elif anchor == "va_ratio" and ratio is not None:
                out = self.term(acc, "output")
                status = "ready" if out else "blocked"
                anchor_value = (out * ratio) if out else None
            else:
                status, anchor_value = "blocked", None
            rows.append({"partition": pid, "anchor": anchor or "none",
                         "status": status, "anchor_value": anchor_value,
                         "va_ratio": ratio, "note": note,
                         "benchmark": rule.get("benchmark", "")})
        # 登记为行业池、但这份账里连规则都没有的分区：也是缺口，不能静默
        for p in self._partitions or []:
            pid = p.get("id", "")
            if not pid or pid in seen:
                continue
            rows.append({"partition": pid, "anchor": "", "status": "unruled",
                         "anchor_value": None, "va_ratio": self.va_ratio(pid),
                         "note": "", "benchmark": ""})
        rows.sort(key=lambda r: ({"ready": 0, "blocked": 1, "unruled": 2}[r["status"]],
                                 r["partition"]))
        return rows

    def summary(self) -> dict:
        ids = [p.get("id") for p in self._partitions or [] if p.get("id")]
        ident = [self.identity(pid) for pid in ids]
        counts: Dict[str, int] = {}
        for r in ident:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        feas = self.pool_feasibility()
        fcounts: Dict[str, int] = {}
        for r in feas:
            fcounts[r["status"]] = fcounts.get(r["status"], 0) + 1
        va_total = sum(r["value_added"] or 0 for r in ident)
        return {
            "loaded": bool(self.loaded),
            "year": self.year,
            "accounts": len(self.accounts),
            "identity_counts": counts,
            "va_total_cny": va_total,
            "pool_counts": fcounts,
            "pool_ready": [r["partition"] for r in feas if r["status"] == "ready"],
            "tolerance": self.tolerance,
        }

    # ------------------------------------------------------------ validate
    # ------------------------------------------------- 中间投入构成：接进口
    def input_plan(self, db=None) -> List[dict]:
        """中间投入构成还缺什么、缺到哪一步、下一步该接哪张表。

        上一轮留下的第四个坑是「中间投入构成 0 个分区有」——建筑业那 23 万亿只知道
        总额，不知道切成建材/机械/分包各多少。卡点不是数据源找不到，是**接了没有
        落点**：知道"建材 8 万亿"之后放哪里？用来干什么？

        所以这里不急着填数，先把接入口立起来：每一条缺失都写清
          need    要找什么口径（不是"中间投入"，是"建筑业中间使用列"）
          source  该去哪张表 / 哪个部门要
          feeds   接进来之后能支撑什么判断（否则补进来也只是堆数）
        """
        schema = []
        for pid, acc in self.accounts.items():
            mid = self.term(acc, "intermediate")
            # inputs 已在 `_normalize_account` 归一，这里不再二次 dict_list：
            # 同一份数据两次归一 = 同一个 problem 报两遍。
            inputs = acc.get("inputs") or []
            if inputs:
                continue
            schema.append({
                "partition": pid,
                "intermediate": mid,
                "declared_complete": bool(acc.get("complete")),
                "need": self.missing_reason(pid, "inputs") or "",
                "blocks": ("行业池切分" if mid else "生产法三端"),
            })
        schema.sort(key=lambda r: (-(r["intermediate"] or 0), r["partition"]))
        return schema

    def dedup_ledger(self) -> List[dict]:
        """某分区被别人当作中间投入引用的合计，与它自己的总产出比。

        这是"去重"的关门条件（validate 4-b 用的同一个算式），单独给一份是为了让
        补构成的人**先看一眼再填**：一个分区的投入已经被别人引用掉 80% 时，
        再往它头上加供给，只会让超产报错。
        """
        supplied: Dict[str, float] = {}
        by_consumer: Dict[str, List[str]] = {}
        for pid, acc in self.accounts.items():
            # 走 `_load` 归一过的 inputs，不再裸迭代：裸 list 遇到
            # `inputs: 建材` 会逐字迭代成「建」「材」，`(it or {}).get` 打在 str 上。
            for it in acc.get("inputs") or []:
                src = (it or {}).get("from") or ""
                v = self._input_amount(it, pid)
                if not src or not v:
                    continue
                supplied[src] = supplied.get(src, 0.0) + v
                by_consumer.setdefault(src, []).append(pid)
        rows: List[dict] = []
        for src, total in supplied.items():
            own = self.term(self.accounts.get(src) or {}, "output")
            rows.append({
                "partition": src,
                "supplied_cny": total,
                "own_output_cny": own,
                "ratio": (total / own) if own else None,
                "consumers": sorted(by_consumer.get(src, [])),
            })
        rows.sort(key=lambda r: (-(r["supplied_cny"] or 0), r["partition"]))
        return rows

    def validate(self) -> List[str]:
        """投入产出账自检：每一端都要能对上，每一处重复计都要被拦住。"""
        problems: List[str] = add_all([], self.load_problems)
        if not os.path.exists(self.path):
            problems.append(
                f"未读到投入产出账: {self.path}（数据源缺失，自检不能视为通过）")
        elif not self.loaded:
            problems.append(
                f"投入产出账是空账: {self.path}"
                f"（文件在但没有任何账户——空账验不出任何恒等式）")

        known = {p.get("id") for p in (self._partitions or []) if p.get("id")}

        # 1. 账户：分区存在、三端数值合法、missing 键合法
        for pid, acc in self.accounts.items():
            if known and pid not in known:
                problems.append(
                    f"投入产出账里的分区 {pid} 不是已知分区（悬空账户，永远查不到）")
            for name in TERMS:
                cell = acc.get(name)
                if cell is None:
                    continue
                if not isinstance(cell, dict):
                    problems.append(
                        f"分区 {pid} 的 {name} 应是对象（含 cny/basis/source），"
                        f"实际是 {type(cell).__name__}")
                    continue
                v = self.term(acc, name)
                if v is None:
                    problems.append(
                        f"分区 {pid} 的 {name} 缺少 cny 数值"
                        f"（空的一端请整个省略，并在 missing 里写原因）")
                elif v < 0:
                    problems.append(
                        f"分区 {pid} 的 {name}={v:,.0f} 为负"
                        f"（生产法三端都不该为负；负值说明口径取错了）")
            for key in (acc.get("missing") or {}):
                if key not in TERMS + ("inputs",):
                    problems.append(
                        f"分区 {pid} 的 missing 键 {key!r} 不是 "
                        f"{list(TERMS) + ['inputs']} 之一"
                        f"（拼错会让该端静默变成「未填原因」）")
            ratio = acc.get("va_ratio")
            if isinstance(ratio, (int, float)) and not isinstance(ratio, bool):
                if not (0 < ratio < 1):
                    problems.append(
                        f"分区 {pid} 的 va_ratio={ratio} 不在 (0,1)"
                        f"（增加值率是比值，超过 1 说明拿总产值当分子了）")

        # 2. 生产法恒等式：对不上就报；缺一端必须写清为什么
        for pid in self.accounts:
            r = self.identity(pid)
            if r["status"] == "zero_output":
                problems.append(
                    f"分区 {pid} 的总产出填了 0，但增加值 {_wan(r['value_added'])} + "
                    f"中间投入 {_wan(r['intermediate'])} 不为 0"
                    f"（报了增加值/中间投入却说总产出 0，这本身就是数据错——"
                    f"0 是实测值不是缺失，缺的一端请整个省略并在 missing 里写原因）")
            elif r["status"] == "zero_rhs":
                problems.append(
                    f"分区 {pid} 的增加值 {_wan(r['value_added'])} + 中间投入 "
                    f"{_wan(r['intermediate'])} 合计为 0，而总产出是 "
                    f"{_wan(r['output'])}"
                    f"（生产法三端里有两端是 0，恒等式算不出偏差——"
                    f"这两端要么该整个省略并写 missing 原因，要么取错了口径）")
            elif r["status"] == "gap":
                # deviation 理论上此时一定不是 None；仍按 None 兜一次：
                # 校验器自己 traceback 是最坏的结果（既不是"数据坏了"也不是绿）。
                dev = (f"{r['deviation']:+.1%}" if r["deviation"] is not None
                       else "算不出（总产出为 0）")
                problems.append(
                    f"分区 {pid} 的生产法对不上：总产出 {_wan(r['output'])} ≠ "
                    f"增加值 {_wan(r['value_added'])} + 中间投入 "
                    f"{_wan(r['intermediate'])}，偏差 {dev} > "
                    f"{self.tolerance:.0%}（三边不同源，必有一个是别的口径）")
            elif r["status"] == "partial":
                miss = [n for n in TERMS if self.term(self.accounts[pid], n) is None]
                unexplained = [n for n in miss if not self.missing_reason(pid, n)]
                if unexplained:
                    problems.append(
                        f"分区 {pid} 的 {unexplained} 缺失但没写原因"
                        f"（说不出这一端为什么不填，等于保证它永远对不上）")

        # 3. 有产值的分区必须在这张账里有落点：漏一个就是"这个数没有生产法解释"
        for p in self._partitions or []:
            pid = p.get("id", "")
            if not pid or not p.get("gdp_cny"):
                continue
            if pid in self.accounts:
                continue
            problems.append(
                f"分区 {pid} 有产值但没在 industry-input-output.yaml 里出现"
                f"（没有生产法解释＝这个数切分时必然重复计，而且没人知道）")

        # 4-a. 中间投入构成合计 = 中间投入总额（声明 complete 时）
        for pid, acc in self.accounts.items():
            # inputs 已在 `_normalize_account` 归一，这里不再二次 dict_list：
            # 同一份数据两次归一 = 同一个 problem 报两遍。
            inputs = acc.get("inputs") or []
            mid = self.term(acc, "intermediate")
            if not inputs:
                continue
            s = 0.0
            for it in inputs:
                v = self._input_amount(it, pid)
                if v is None:
                    problems.append(
                        f"分区 {pid} 的中间投入构成有一条取不到金额：{it}")
                    continue
                s += v
            if acc.get("complete") and mid:
                dev = (s - mid) / mid if mid else 0
                if abs(dev) > self.tolerance:
                    problems.append(
                        f"分区 {pid} 的中间投入构成合计 {_wan(s)} 与中间投入总额 "
                        f"{_wan(mid)} 偏差 {dev:+.1%}（声明 complete 就必须对上，"
                        f"否则两套数必有一天打架）")

        # 4-b. 供给上界：某分区作为投入方出现的合计 ≤ 它自己的总产出
        supplied: Dict[str, float] = {}
        for pid, acc in self.accounts.items():
            for it in acc.get("inputs") or []:
                src = (it or {}).get("from") or ""
                v = self._input_amount(it, pid)
                if src and v:
                    supplied[src] = supplied.get(src, 0.0) + v
        for src, total in supplied.items():
            own = self.term(self.accounts.get(src) or {}, "output")
            if own and total > own * (1 + self.tolerance):
                problems.append(
                    f"分区 {src} 被当作中间投入供给方共 {_wan(total)}，"
                    f"超过它自己的总产出 {_wan(own)}"
                    f"（供不出比自己产出更多的东西——这是重复计的关门条件）")

        # 4-c. 增加值合计 ≤ 全国 GDP：超了就是同一笔价值被算了两遍
        va_total = sum(self.term(acc, "value_added") or 0
                       for acc in self.accounts.values())
        gdp = self._national_gdp()
        if gdp and va_total > gdp * (1 + self.tolerance):
            problems.append(
                f"投入产出账里的增加值合计 {_wan(va_total)} 超过全国 GDP "
                f"{_wan(gdp)}（同一笔价值被两个分区各算了一遍）")

        # 5. 池切分规则：分区合法、锚点在枚举里、ready 必须有锚值
        seen: Dict[str, int] = {}
        for r in self.pool_rules:
            pid = r.get("partition") or ""
            if not pid:
                problems.append("池切分规则缺少 partition")
                continue
            seen[pid] = seen.get(pid, 0) + 1
            if known and pid not in known:
                problems.append(f"池切分规则指向不存在的分区 {pid}")
            anchor = r.get("anchor") or ""
            if anchor not in ANCHORS:
                problems.append(
                    f"池 {pid} 的 anchor={anchor!r} 不在 {list(ANCHORS)} 中"
                    f"（锚点决定能不能切，写错会让不可切的池看起来可切）")
        for pid, cnt in seen.items():
            if cnt > 1:
                problems.append(f"池 {pid} 有 {cnt} 条切分规则（互相矛盾，只许一条）")
        return problems

    def _input_amount(self, item: dict, pid: str = "") -> Optional[float]:
        """中间投入构成一条的金额：给 cny 直接取；给 share 则乘中间投入总额。

        `share` 的存在是为了"只知道结构、不知道金额"的场景（投入产出表的直接
        消耗系数就长这样）。两条都给时以 cny 为准，share 忽略——同一件事存两套
        数必有一天打架。

        `share` 分支早先写成 `return None if not isinstance(...) else None`，
        两个分支都返回 None：**按文档写 `{from: x, share: 0.5}` 反而报
        「取不到金额」，同时构成合计比中间投入总额少 100%**。
        按文档写数据却报错，比不支持更坏——所以这里真的实现它。
        """
        v = (item or {}).get("cny")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
        share = (item or {}).get("share")
        if isinstance(share, bool) or not isinstance(share, (int, float)):
            return None
        acc = self.accounts.get(pid) or {}
        mid = self.term(acc, "intermediate")
        if mid is None:
            # 没有中间投入总额就无从折算。这时返回 None 而由 validate 报
            # 「缺 intermediate」比编一个数好：编出来的份额乘出来的金额，
            # 每个数单看都合理，加起来才不对。
            return None
        return float(share) * mid

    def _national_gdp(self) -> Optional[float]:
        """全国 GDP：从官方基准借 gdp-total，不在这里抄第二份。

        不抄的理由：GDP 每年修订，两处各存一份时，跑对账的人和跑汇总的人会拿到
        两个不同的分母，而且没人知道哪个对。
        """
        try:
            from .official_baseline import OfficialBaseline
            base = OfficialBaseline(self.data_dir)
            bench = base.benchmark("gdp-total")
            rec = base.series_value(bench, self.year)
            v = (rec or {}).get("value_cny")
            return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) \
                else None
        except Exception:  # noqa: BLE001 - 借不到分母不该让自检崩
            return None


def _wan(v) -> str:
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return "—"
    return f"{v / 1e8:,.0f} 亿元"
