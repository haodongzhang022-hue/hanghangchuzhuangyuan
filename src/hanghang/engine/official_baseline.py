"""M11 官方口径基准 · 逐年对表（official_baseline）

## 一句话

`gdp_confidence: high` 原来是一句**自我声明**：谁都可以标 high，没人能证明。
这份账把它变成**可核对**的：分区产值 ←对比→ 官方口径的同一笔钱，同口径、同年份、
有出处。对不上就报，口径不同就明说不可比。

## 三种对表关系（relation）

| relation | 含义 | 比什么 |
|---|---|---|
| `equal` | 分区范围 = 官方范围 | 偏差 `|分区-官方|/官方 ≤ tolerance` |
| `envelope` | 分区 ⊆ 官方（官方是门类总量） | 上界 `分区 ≤ 官方×(1+tolerance)` |
| `incomparable` | 两者口径不同，**不能相减** | 只登记关系，不做数值比较 |

`incomparable` 不是偷懒的出口：它必须写 `reason`，而且**该分区不得标 high**
——口径不同就不配当"可对外引用"的背书。软件研发 6 万亿（软件业务收入）对
信息服务业增加值 5.5 万亿，收入必然大于增加值，相减得到的"差额"没有经济含义；
这类关系要显式写下来，否则下一个人一定会拿它当"漏了 0.5 万亿"。

## 为什么按年存

单年对表只证明"这一年碰巧对上"。官方表值每年修订（初步核算 → 最终核实），
所以基准按年存 series，分区用 `gdp_year` 声明自己对齐哪一年。
有两年以上才谈得上逐年对齐与同比 `yoy`。

## 为什么要有 unlinked

"没有可比口径"本身是结论，但**必须说出来**：说不出为什么没有，等于这个行业的
数永远没人验过而没人知道。所以每个有产值的分区要么在 `links` 里，要么在
`unlinked` 的分组里，一个都不能少（validate 第 24 条）。
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional

import yaml

from ._shape import add_all, dict_list

# 三种对表关系。刻意只有三种：再多就把"不一样"说成了一堆同义词。
RELATIONS = ("equal", "envelope", "incomparable")

# 基准的来历，决定它能不能给 high 背书。**比数值本身更重要**：
#   published   逐表抄自公开统计表 → 唯一能背书 high 的一档
#   recalled    凭量级回忆，未逐表核对 → 数值可能对，但没有可追溯的表页
#   backfilled  由分区现有估算反推 → 让对表变成循环论证（自己和自己比，永远 0%），
#               得出的"对上"什么也没证明，却看起来像证据
ORIGINS = ("published", "recalled", "backfilled")
# 能背书 high 的来历
ORIGIN_TRUSTED = ("published",)
# 分区侧对齐年份缺省值：与 partition.gdp_year_basis 的写法一致（区间取末年）
DEFAULT_TOLERANCE = 0.10


class OfficialBaseline:
    """官方口径基准：逐年表值 + 分区↔基准对表关系 + 没可比口径的分组说明。"""

    def __init__(self, data_dir: Optional[str] = None,
                 partitions: Optional[List[dict]] = None):
        self.data_dir = data_dir or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "../../../data")
        self.path = os.path.join(self.data_dir, "industry-official-baseline.yaml")
        self.version = "0.1"
        self.updated_at = ""
        self.years: List[int] = []
        self.tolerance = DEFAULT_TOLERANCE
        self.benchmarks: List[dict] = []
        self.links: List[dict] = []
        self.unlinked: List[dict] = []
        # 文件在、内容只有注释时 `os.path.exists` 照样 True，而每条校验都"通过"。
        # 缺文件与空账要分开报，而且都是硬失败（与 money_flow 同一条规矩）。
        self.loaded = False
        # 结构写歪记这里，由 validate() 报
        self.load_problems: List[str] = []
        self._partitions = partitions or []
        # 文件级 gdp_year_basis（partition 上没写时回落到它）。由 IndustryDatabase
        # 从 industry-partitions.yaml 顶层读出来传进来，不让本模块去读第二个文件。
        self.default_year_basis = ""
        self._load()

    # ---------------------------------------------------------------- load
    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        with open(self.path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        self.version = str(data.get("version", self.version))
        self.updated_at = str(data.get("updated_at", ""))
        self.years = [int(y) for y in (data.get("years") or []) if _is_int(y)]
        tol = data.get("tolerance")
        if isinstance(tol, (int, float)) and not isinstance(tol, bool) and tol > 0:
            self.tolerance = float(tol)
        where = os.path.basename(self.path)
        self.benchmarks = dict_list(data.get("benchmarks"), "benchmarks",
                                    self.load_problems, where)
        self.links = dict_list(data.get("links"), "links", self.load_problems, where)
        self.unlinked = dict_list(data.get("unlinked"), "unlinked",
                                  self.load_problems, where)
        self.loaded = bool(self.benchmarks or self.links)

    def bind(self, partitions: List[dict],
             default_year_basis: str = "") -> None:
        self._partitions = partitions
        if default_year_basis:
            self.default_year_basis = default_year_basis

    # ------------------------------------------------------------- lookups
    def benchmark(self, bid: str) -> Optional[dict]:
        for b in self.benchmarks:
            if b.get("id") == bid:
                return b
        return None

    @staticmethod
    def series_value(bench: dict, year: Optional[int]) -> Optional[dict]:
        """取某一年的官方表值。没写 year 时取最新一年（series 末条）。

        不取"最新一条"以外的口径（如平均值/中位数）：对表比的是同一年同一笔钱，
        拿平均去比等于把两年的修订差算进偏差里。
        """
        rows = [r for r in (bench.get("series") or []) if _is_int(r.get("year"))]
        if not rows:
            return None
        if year is None:
            return rows[-1]
        for r in rows:
            if int(r["year"]) == int(year):
                return r
        return None

    def yoy(self, bid: str) -> Optional[float]:
        """基准的同比增速：两年以上 series 才有。少于两年返回 None，不去凑。"""
        bench = self.benchmark(bid)
        if not bench:
            return None
        rows = [r for r in (bench.get("series") or [])
                if _is_int(r.get("year")) and _is_num(r.get("value_cny"))]
        if len(rows) < 2:
            return None
        prev, last = rows[-2], rows[-1]
        if not prev["value_cny"]:
            return None
        return (last["value_cny"] - prev["value_cny"]) / prev["value_cny"]

    def link_of(self, part_id: str) -> Optional[dict]:
        for lk in self.links:
            if lk.get("partition") == part_id:
                return lk
        return None

    def unlinked_reason(self, part_id: str) -> str:
        """这个分区为什么没有官方可比口径。返回空串 = 既没接也没说（校验报出）。"""
        for group in self.unlinked:
            if part_id in (group.get("partitions") or []):
                return str(group.get("reason", "") or "")
        return ""

    # ----------------------------------------------------------- part year
    def part_year(self, part: dict) -> tuple:
        """分区对齐哪一年，以及这个年份是怎么定的 → ``(year, source)``。

        优先级：
          1. `gdp_year`（显式钉死）→ ``("declared")``
          2. `gdp_year_basis` 区间（"2023-2024"，缺省回落文件级同名声明）
             **在基准已有年份里**取末年 → ``("basis_range")``。区间声明 2023-2024、
             基准录到 2023 时取 2023，
             而不是硬取 2024 —— 硬取会得到"官方没这一年的数"，而那看起来像
             "对不上"，其实只是我们的基准还没录。
          3. 都没有 → ``(None, "")``

        为什么要回落：41 个分区的年份原先只写在 `gdp_year_basis` 这个自由文本里，
        机器读不到，"逐年对齐"就无从校验。回落让老数据不用批量回填，新数据还能
        用 `gdp_year` 显式钉死；`source` 把"这个年份是声明的还是推出来的"写在
        对表结论里，避免推出来的年份被当成声明过的。
        """
        y = part.get("gdp_year")
        if _is_int(y):
            return int(y), "declared"
        basis = str(part.get("gdp_year_basis", "") or self.default_year_basis)
        nums = sorted({int(x) for x in _years_in(basis)})
        if not nums:
            return None, ""
        known = [n for n in nums if not self.years or n in self.years]
        return (known[-1] if known else nums[-1]), "basis_range"

    # --------------------------------------------------------------- check
    def compare(self) -> List[dict]:
        """逐分区对表。每条给出：谁对谁、什么关系、偏差、结论。

        结论只有四种：`ok` / `gap` / `incomparable` / `no_series`
        —— 别用空字符串当"没问题"：那和"没对过"分不清。
        """
        rows: List[dict] = []
        for p in self._partitions or []:
            pid = p.get("id", "")
            if not pid:
                continue
            val = p.get("gdp_cny")
            lk = self.link_of(pid)
            if not lk:
                rows.append({"partition": pid, "benchmark": "", "relation": "",
                             "status": "unlinked" if self.unlinked_reason(pid)
                             else "unexplained",
                             "part_value": val, "bench_value": None,
                             "deviation": None, "reason": self.unlinked_reason(pid)})
                continue
            bid = lk.get("benchmark", "")
            bench = self.benchmark(bid)
            year, year_source = self.part_year(p)
            rec = self.series_value(bench, year) if bench else None
            row = {"partition": pid, "benchmark": bid,
                   "relation": lk.get("relation", ""),
                   "year": year, "year_source": year_source, "part_value": val,
                   "bench_value": (rec or {}).get("value_cny"),
                   "bench_year": (rec or {}).get("year"),
                   "tolerance": lk.get("tolerance", self.tolerance),
                   "reason": lk.get("reason", ""), "status": "", "deviation": None}
            if row["relation"] == "incomparable":
                row["status"] = "incomparable"
                rows.append(row)
                continue
            if rec is None or not _is_num(row["bench_value"]) or not row["bench_value"]:
                # 分区声明 2023、基准只到 2022 → 没有可比表值。这不是"对上了"。
                row["status"] = "no_series"
                rows.append(row)
                continue
            if not _is_num(val):
                row["status"] = "no_value"
                rows.append(row)
                continue
            tol = float(row["tolerance"] or DEFAULT_TOLERANCE)
            dev = (val - row["bench_value"]) / row["bench_value"]
            row["deviation"] = dev
            if row["relation"] == "envelope":
                # 上界校验：分区比门类还大 = 重复计或口径混了
                row["status"] = "ok" if dev <= tol else "gap"
            else:
                row["status"] = "ok" if abs(dev) <= tol else "gap"
            rows.append(row)
        return rows

    def confidence_of(self, part_id: str) -> str:
        """按对表结果给出**可辩护**的置信度上限。

        high 只留给"同口径 + 同年份 + 偏差在容差内"的分区。对不上、口径不同、
        没有表值，一律不许 high —— 现在 gdp_confidence 是手写的自我声明，
        这里给出机器算得出来的那一份。
        """
        rows = [r for r in self.compare() if r["partition"] == part_id]
        if not rows:
            return "low"
        r = rows[0]
        if r["status"] == "ok":
            # 对上还不够：基准本身得是逐表抄来的公开值。反推出来的"官方值"
            # 与分区同源，比出来永远 0% 偏差 —— 那是一致的错，不是一致的对。
            bench = self.benchmark(r.get("benchmark", "")) or {}
            origin = bench.get("origin")
            return "high" if origin in ORIGIN_TRUSTED else "medium"
        if r["status"] in ("incomparable", "no_series", "no_value", "unlinked"):
            return "medium" if r["status"] != "unlinked" else "low"
        return "low" if r["status"] == "gap" else "low"

    def summary(self) -> dict:
        rows = self.compare()
        counts: Dict[str, int] = {}
        for r in rows:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        return {
            "loaded": bool(self.loaded),
            "years": list(self.years),
            "benchmarks": len(self.benchmarks),
            "linked_partitions": len(self.links),
            "status_counts": counts,
            "checked": sum(1 for r in rows if r["status"] in ("ok", "gap")),
            "with_series": sum(1 for r in self.benchmarks if r.get("series")),
            # 基准系列的年份覆盖：只有一年 = 只有单年对表，谈不上逐年
            "series_two_year": sum(1 for b in self.benchmarks
                                   if len(b.get("series") or []) >= 2),
        }

    # ------------------------------------------------------------ validate
    def validate(self) -> List[str]:
        """对表账自检。每一条都对应一种"数字看着有出处、其实没人验过"的形态。"""
        problems: List[str] = add_all([], self.load_problems)
        if not os.path.exists(self.path):
            problems.append(
                f"未读到官方口径基准: {self.path}（数据源缺失，自检不能视为通过）")
        elif not self.loaded:
            problems.append(
                f"官方口径基准是空账: {self.path}"
                f"（文件在但没有任何基准/对表关系——空账验不出任何数）")

        # 1. 基准：id 唯一、kind/axis 合法、series 年份合法且不重复、值为正
        seen: Dict[str, int] = {}
        for b in self.benchmarks:
            bid = b.get("id") or ""
            if not bid:
                problems.append("官方基准缺少 id（对表关系无法引用）")
                continue
            seen[bid] = seen.get(bid, 0) + 1
            origin = b.get("origin")
            if origin not in ORIGINS:
                problems.append(
                    f"基准 {bid} 的 origin={origin!r} 不在 {list(ORIGINS)} 中"
                    f"（来历不明就无法判断它能不能背书 high，写不清就不许当证据）")
            series = b.get("series") or []
            if not series:
                problems.append(
                    f"基准 {bid} 没有任何 series（没有逐年表值，就没有可对的东西）")
            years = []
            for r in series:
                if not _is_int(r.get("year")):
                    problems.append(f"基准 {bid} 的 series 年份不是整数: {r.get('year')!r}")
                    continue
                years.append(int(r["year"]))
                val = r.get("value_cny")
                if not _is_num(val):
                    problems.append(
                        f"基准 {bid} 的 {r['year']} 年值不是数值: {val!r}")
                elif val <= 0:
                    problems.append(
                        f"基准 {bid} 的 {r['year']} 年值 {val} 不为正"
                        f"（表值可以缺，但不该是 0 或负数）")
                if not r.get("source"):
                    problems.append(
                        f"基准 {bid} 的 {r['year']} 年没写出处"
                        f"（对表的价值全在出处，没出处的数等于自己写的）")
            dup = {y for y in years if years.count(y) > 1}
            if dup:
                problems.append(f"基准 {bid} 的 series 年份重复: {sorted(dup)}")
            if self.years:
                extra = [y for y in years if y not in self.years]
                if extra:
                    problems.append(
                        f"基准 {bid} 的 series 年份 {extra} 不在全局 years "
                        f"{self.years} 里（年份不在册，同比与对齐都会算错）")
        for bid, cnt in seen.items():
            if cnt > 1:
                problems.append(f"官方基准 id 重复: {bid} 出现 {cnt} 次")

        # 2. 对表关系：分区存在、基准存在、relation 合法、incomparable 必有 reason
        known = {p.get("id") for p in (self._partitions or []) if p.get("id")}
        link_seen: Dict[str, int] = {}
        for lk in self.links:
            pid = lk.get("partition") or ""
            if not pid:
                problems.append("对表关系缺少 partition（不知道是谁在对）")
                continue
            link_seen[pid] = link_seen.get(pid, 0) + 1
            if known and pid not in known:
                problems.append(
                    f"对表关系指向不存在的分区 {pid}（悬空关系，永远对不到东西）")
            bid = lk.get("benchmark") or ""
            if not self.benchmark(bid):
                problems.append(f"分区 {pid} 对表指向不存在的基准 {bid!r}")
            rel = lk.get("relation") or ""
            if rel not in RELATIONS:
                problems.append(
                    f"分区 {pid} 的 relation={rel!r} 不在 {list(RELATIONS)} 中")
            if rel == "incomparable" and not lk.get("reason"):
                problems.append(
                    f"分区 {pid} 声明 incomparable 但没写 reason"
                    f"（口径不同就必须说清哪里不同，否则下一个会当它漏了钱）")
            va = lk.get("value_added_benchmark")
            if va and not self.benchmark(va):
                problems.append(
                    f"分区 {pid} 的 value_added_benchmark={va!r} 不存在")
        for pid, cnt in link_seen.items():
            if cnt > 1:
                problems.append(
                    f"分区 {pid} 有 {cnt} 条对表关系（一个分区只能对一份官方口径，"
                    f"两条会给出两个互相矛盾的结论）")

        # 3. 每个有产值的分区必须"有对表"或"有说明为什么没有"
        for p in self._partitions or []:
            pid = p.get("id", "")
            if not pid or not p.get("gdp_cny"):
                continue
            if self.link_of(pid) or self.unlinked_reason(pid):
                continue
            problems.append(
                f"分区 {pid} 有产值但既没接官方基准、也没写为什么没有可比口径"
                f"（没有出处的数，就是没人验过的数）")

        # 4. 对表结论：gap 必须报（数字与官方对不上，且没人解释）
        for r in self.compare():
            if r["status"] == "gap":
                problems.append(
                    f"分区 {r['partition']} 的产值 {_wan(r['part_value'])} 与官方基准 "
                    f"{r['benchmark']}（{r['bench_year']} 年 {_wan(r['bench_value'])}）"
                    f"偏差 {r['deviation']:+.1%}，超出容差 {r['tolerance']:.0%}"
                    f"（{r['relation']} 关系；要么改数，要么改口径说明）")

        # 5. 标了 high 就必须有通过的对表：否则 high 是自我声明
        for p in self._partitions or []:
            if p.get("gdp_confidence") != "high" or not p.get("gdp_cny"):
                continue
            r = next((x for x in self.compare()
                      if x["partition"] == p.get("id")), None)
            bench = self.benchmark((r or {}).get("benchmark", "")) or {}
            origin = bench.get("origin")
            if r and r["status"] == "ok" and origin not in ORIGIN_TRUSTED:
                problems.append(
                    f"分区 {p.get('id')} 标了 gdp_confidence=high，但它对表的基准 "
                    f"{r['benchmark']} 的 origin={origin!r} 不是逐表抄来的公开值"
                    f"（{list(ORIGIN_TRUSTED)} 才能背书 high；反推或回忆的基准"
                    f"与分区同源，比出来的一致什么也没证明）")
                continue
            if not r or r["status"] != "ok":
                why = {"incomparable": "口径与官方不同（不可比）",
                       "no_series": "官方基准没有该年份的表值",
                       "unlinked": "没有接官方基准",
                       "gap": "与官方基准偏差超容差",
                       "unexplained": "既没接基准也没写原因",
                       "no_value": "分区没有产值"}.get(
                           (r or {}).get("status", ""), "没有对表记录")
                problems.append(
                    f"分区 {p.get('id')} 标了 gdp_confidence=high，但{why}"
                    f"（high 只能由通过的对表背书，不能自己写）")
        return problems


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _years_in(text: str) -> List[str]:
    import re
    return re.findall(r"(19|20)\d{2}", text or "") and \
        re.findall(r"(?:19|20)\d{2}", text or "")


def _wan(v) -> str:
    """显示用：元 → 亿元。只用于报错文案，不参与任何计算。"""
    if not _is_num(v):
        return "—"
    return f"{v / 1e8:,.0f} 亿元"
