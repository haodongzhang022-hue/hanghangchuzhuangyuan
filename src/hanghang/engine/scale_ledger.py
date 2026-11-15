"""M11 行业规模账 · 六口径可见度与交叉验证（scale_ledger）

## 要解决的问题

**一个大行业不该因为"产值没统计"就在表里整体隐身。**

产值（增加值）是最难拿的一个口径：全国只有 ~20 个门类有官方增加值，
细分行业往往没有独立统计。但它有别的痕迹——利润总额、资产总计、
上市板块估值、从业人数、能源/水/原材料消耗。只要**任一口径有数**，
这个行业就还在表里，能排序、能比较、能进分母。

所以口径不是"更精确的同一个数"，而是**同一批钱的六个侧面**：

| 口径 | 回答什么 | 谁最常给 |
|---|---|---|
| `gdp` | 一年新增多少价值 | 统计局分行业增加值 |
| `profit` | 兜里剩下多少 | 规上企业利润总额 / 上市公司年报 |
| `asset` | 压着多少钱 | 规上企业资产总计 / 资产负债表 |
| `valuation` | 市场给多少钱 | 上市板块总市值 / 一级市场估值 |
| `employment` | 多少人在干 | 统计年鉴从业人数 |
| `resource` | 吃掉多少实物 | 能源消费/用电/用水/原料 |

## 三条立场（沿用本仓库既有规矩）

1. **没有口径就不填数字。** `null ≠ 0`。缺了写 `missing` 原因，不编。
2. **已存在单源的不重复存。** `gdp` 读 `partition.gdp_cny + gdp_kind`，
   `employment` 读 `partition.employment`。本文件只补另外四个口径——
   同一件事存两份，迟早对不上，而且没人知道哪份是对的。
3. **交叉验证只抓数量级错。** 两个口径互推，抓的是「万元填成元」
   「把 GMV 当营业收入」「人数填成人数×1e4」这类错。这类错数字越大
   越像真的，单看任何一个都发现不了，只能靠互推。

## 为什么不是硬校验

行业之间差异本来就大（金融业资产是增加值的 150 倍，律所没有资产周转问题）。
比值窗口只能设成数量级（10 倍以上偏差才报），**宁可漏报，不可误报**——
误报一次，整条校验就会被当成噪音关掉，那才是真的失守。
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional

import yaml

from ._shape import add_all, dict_list, mapping

# 六个口径。顺序即"从最好拿到最难拿"：可见度报告按这个顺序摊开。
SCALE_METRICS = ("gdp", "employment", "profit", "asset", "valuation", "resource")
# 存储在 industry-scales.yaml 里的四个（另两个在 partition 上，见模块 docstring）
LEDGER_METRICS = ("profit", "asset", "valuation", "resource")
METRIC_LABELS = {
    "gdp": "年产值/增加值",
    "employment": "从业人数",
    "profit": "盈利规模",
    "asset": "资产规模",
    "valuation": "估值规模",
    "resource": "资源消耗",
}
CONFIDENCE = ("high", "medium", "low")

# 可见度等级：命中几个口径
#   full     ≥4 个口径有数 —— 六个侧面里看清了大半，可以跨行业比
#   partial  1-3 个 —— 至少没隐身，能排序能定位，缺口写着
#   hidden   0 个 —— 必须显式说明为什么（没有独立口径 / 并入别的分区统计）
VISIBILITY_FULL = 4
VISIBILITY_LEVELS = ("full", "partial", "hidden")

# 资源口径的常用实物单位。不折算成钱：把"耗电 800 亿度"折成人民币要选电价，
# 一选就把一件实测的事变成一件估算的事，得不偿失。
RESOURCE_UNITS = ("tce", "kwh", "ton", "ton_water", "m3", "gwh")


class ScaleLedger:
    """行业规模账：六口径槽位 + 可见度 + 数量级交叉验证。

    `data/industry-scales.yaml` 只存 profit/asset/valuation/resource；
    gdp/employment 从 partition 现读（单一来源）。
    """

    # ---- 交叉验证窗口（只抓数量级错，不抓行业差异）----
    # 利润率 profit/gdp：按 gdp 口径分档。增加值口径下利润是增加值的一部分，
    # 营收/GMV 口径下利润是收入的一部分 —— 两档上限不一样。
    PROFIT_MARGIN_WINDOW = {
        "value_added": (-0.6, 1.2),
        "revenue": (-0.8, 0.9),
        "gross_output": (-0.8, 0.9),
        "market_size": (-0.8, 0.9),
        "gmv": (-0.8, 0.9),
    }
    # 人均产出（元/人）：窗口开得很宽（1 万 ~ 5 亿），只为抓 1e4 级别的错位
    OUTPUT_PER_HEAD_WINDOW = (1e4, 5e8)
    OUTPUT_PER_HEAD_KINDS = ("value_added", "revenue", "gross_output")
    # 估值倍数：PE(估值/利润) 与 PS(估值/产值)
    PE_WINDOW = (0.5, 500.0)
    PS_WINDOW = (0.01, 200.0)

    def __init__(self, data_dir: Optional[str] = None,
                 partitions: Optional[List[dict]] = None):
        # 默认目录：本文件在 src/hanghang/engine/，仓库根是 ../../../。
        # 早先写成 "../../data" 只到 src/data —— 不带参数构造必然读到空账，
        # 而空账在 CLI/Web 上表现为"六个口径全空 / 零个资金流节点"，
        # 看起来像数据没补，实际是路径错了。
        self.data_dir = data_dir or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "../../../data")
        self.path = os.path.join(self.data_dir, "industry-scales.yaml")
        self.version = "0.1"
        self.updated_at = ""
        self.year_basis = ""
        # partition -> {"profit": {...}, ...}
        self.entries: Dict[str, dict] = {}
        # 结构写歪（列表里混字符串、映射写成标量）记在这里，由 validate() 报。
        # 不在消费点各兜一次：`(it or {})` 只兜得住 None，兜不住字符串，
        # 于是 `industry check` 这个 CI 闸自己 traceback —— 红灯既不是"数据坏了"
        # 也不是"绿"。想到之外的路只能靠入口收口。
        self.load_problems: List[str] = []
        self._load()
        # 传进来的分区表若被后续改动，可见度要跟着变，所以不缓存快照
        self._partitions = partitions

    # ---------------------------------------------------------------- load
    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        with open(self.path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        self.version = str(data.get("version", self.version))
        self.updated_at = str(data.get("updated_at", ""))
        self.year_basis = str(data.get("year_basis", ""))
        where = os.path.basename(self.path)
        for row in dict_list(data.get("scales"), "scales", self.load_problems, where):
            pid = row.get("partition") or ""
            if not pid:
                self.load_problems.append(
                    f"{where} 的 scales 里有一项没有 partition"
                    f"（这一格六口径落点找不到主人）")
                continue
            metrics = {}
            for name in LEDGER_METRICS:
                cell = row.get(name)
                if isinstance(cell, dict):
                    metrics[name] = dict(cell)
                elif cell is not None:
                    self.load_problems.append(
                        f"分区 {pid} 的 {name} 应写成金额映射"
                        f"（如 {{{self.AMOUNT_KEY.get(name, 'cny')!r}: 数值}}），"
                        f"实际是 {type(cell).__name__}: {cell!r}"
                        f"（当成「没填」会让写错的数据静默变空）")
            # 显式声明"这个口径确实没有"，与"忘了填"分开
            if row.get("missing") is not None:
                metrics["_missing"] = mapping(
                    row.get("missing"), f"分区 {pid} 的 missing",
                    self.load_problems, where)
            if row.get("note"):
                metrics["_note"] = row["note"]
            self.entries[pid] = metrics

    def bind(self, partitions: List[dict]) -> None:
        """绑定分区表：可见度与交叉验证都要看 partition 上的 gdp/employment。"""
        self._partitions = partitions

    # ------------------------------------------------------------- lookups
    def partition(self, part_id: str) -> Optional[dict]:
        for p in self._partitions or []:
            if p.get("id") == part_id:
                return p
        return None

    # partition 上的字段名与账本里的键名不同：账本里 gdp 写成 {cny: x}，
    # partition 上是 gdp_cny；就业则是 employment / {wan: x}。
    PARTITION_KEY = {"gdp": "gdp_cny", "employment": "employment"}

    # 每个口径只认一个金额键：`wan` 是就业口径的写法，`value` 是资源口径的写法。
    # 早先这里对所有 key 一视同仁地取，于是 profit 手滑写成 {wan: 9e6} 时
    # `_amount` 照样返回 9e6，而 cross_check 按 profit["cny"] 取 → KeyError，
    # `industry check` 直接 traceback。**校验器自己挂了**是最难查的故障：
    # 红灯既不是"数据坏了"也不是"绿"。
    AMOUNT_KEY = {"gdp": "cny", "employment": "wan",
                  "profit": "cny", "asset": "cny", "valuation": "cny",
                  "resource": "value"}

    @classmethod
    def _amount(cls, cell, name: str = "", partition_side: bool = False
                ) -> Optional[float]:
        """口径值：按口径只认它自己那一个键。缺失/键不对就是 None，不当 0。

        `partition_side=True` 读的是 partition 上的字段名（gdp_cny / employment），
        否则读账本里的键名（cny / wan / value）。两套名字由 PARTITION_KEY
        显式映射，不靠"试着取一遍"——那正是写错键也能静默取到数的来源。
        """
        if not isinstance(cell, dict):
            return None
        if partition_side:
            key = cls.PARTITION_KEY.get(name)
            keys = (key,) if key else ()
        else:
            key = cls.AMOUNT_KEY.get(name)
            keys = (key,) if key else ("cny", "wan", "value")
        for k in keys:
            val = cell.get(k)
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                continue
            return float(val)
        return None

    @classmethod
    def wrong_amount_key(cls, cell, name: str) -> str:
        """金额写在了别的口径的键上（profit 写成 wan 这类）。

        返回那个错误的键名，正确或没写返回空串。数据没错但键写错的后果是
        **这一格静默变空**，而空格的语义是"没统计到"——两件事完全不同。
        """
        if not isinstance(cell, dict):
            return ""
        want = cls.AMOUNT_KEY.get(name)
        if not want or want in cell:
            return ""
        for k in ("cny", "wan", "value"):
            if k in cell:
                return k
        return ""

    def metric(self, part_id: str, name: str) -> Optional[dict]:
        """单个口径的完整记录（含来源/置信度/单位）。无数据返回 None。

        这是"槽位"的读取口：返回 None 不代表"这个行业没有这件事"，
        只代表"这一面还没拿到数"。两者在可见度报告里分开写。
        """
        p = self.partition(part_id) or {}
        if name == "gdp":
            # partition 上的 gdp_cny 可能是字符串（yaml 写错/导入脏数据）。
            # 这里不抛：metric() 是只读出口，CLI/Web/导出都要走它，一份脏数据
            # 不该让看数据的人拿到 traceback。类型错由 industry_db.validate()
            # 第 17-b 条明确报出——数据问题在数据校验里报，不在读取路径上炸。
            val = self._amount(p, "gdp", partition_side=True)
            if val is None:
                return None
            return {"cny": val, "kind": p.get("gdp_kind", ""),
                    "confidence": p.get("gdp_confidence", ""),
                    "basis": p.get("gdp_scope", ""),
                    "source": p.get("gdp_source", "")}
        if name == "employment":
            val = self._amount(p, "employment", partition_side=True)
            if val is None:
                return None
            return {"wan": val,
                    "basis": "从业人员规模",
                    "source": p.get("employment_source", "")}
        cell = (self.entries.get(part_id) or {}).get(name)
        if not isinstance(cell, dict):
            return None
        if self._amount(cell, name) is None:
            return None
        return dict(cell)

    @staticmethod
    def human_resource(value: Optional[float], unit: str = "") -> str:
        """资源消耗是实物量：2,600,000,000 tce 没人读得懂，换成"26.0 亿吨标煤"。

        不折成钱：折成钱要选电价/煤价，一选就把实测变成估算。
        """
        if value is None:
            return "—"
        unit = unit or ""
        if unit == "tce":
            if abs(value) >= 1e8:
                return f"{value / 1e8:,.1f} 亿吨标煤"
            if abs(value) >= 1e4:
                return f"{value / 1e4:,.0f} 万吨标煤"
            return f"{value:,.0f} 吨标煤"
        if unit == "kwh":
            return f"{value / 1e8:,.1f} 亿度" if abs(value) >= 1e8 else f"{value:,.0f} 度"
        if unit == "gwh":
            return f"{value:,.0f} GWh"
        if unit == "ton":
            return f"{value / 1e4:,.0f} 万吨" if abs(value) >= 1e4 else f"{value:,.0f} 吨"
        if unit == "ton_water":
            return f"{value / 1e8:,.1f} 亿吨水" if abs(value) >= 1e8 else f"{value:,.0f} 吨水"
        if unit == "m3":
            return f"{value / 1e8:,.1f} 亿立方米" if abs(value) >= 1e8 else f"{value:,.0f} 立方米"
        return f"{value:,.0f} {unit}".strip()

    def missing_reason(self, part_id: str, name: str) -> str:
        """这个槽位为什么是空的。返回空串 = 既没数也没写原因（由校验报出）。

        gdp / employment 的原因**回落到 partition 上已有的 gdp_scope /
        employment_source**：那两句话本来写的就是"并入某某口径、无独立统计"，
        再在账本里抄一遍，迟早一边改了另一边没改，然后没人知道哪句是真的。
        """
        entry = self.entries.get(part_id) or {}
        miss = entry.get("_missing") or {}
        why = str(miss.get(name, "") or "")
        if why:
            return why
        p = self.partition(part_id) or {}
        if name == "gdp" and p.get("gdp_kind") == "none":
            return str(p.get("gdp_scope", "") or "")
        if name == "employment":
            return str(p.get("employment_source", "") or "")
        return ""

    def visibility(self, part_id: str) -> dict:
        """可见度：六个口径命中几个、缺哪几个、为什么缺。

        这是本模块的核心输出。一个行业只要**任一**口径有数就没隐身，
        与"有没有产值"无关 —— 产值只是其中一格。
        """
        present = [m for m in SCALE_METRICS if self.metric(part_id, m)]
        missing = [m for m in SCALE_METRICS if m not in present]
        if len(present) >= VISIBILITY_FULL:
            level = "full"
        elif present:
            level = "partial"
        else:
            level = "hidden"
        return {
            "partition": part_id,
            "present": present,
            "missing": missing,
            "count": len(present),
            "level": level,
            # 每个缺口都带一句原因，让"没数"和"没这个口径"分开
            "missing_detail": {m: self.missing_reason(part_id, m) or "未填原因"
                               for m in missing},
        }

    def visibility_all(self) -> List[dict]:
        rows = [self.visibility(p.get("id", "")) for p in (self._partitions or [])
                if p.get("id")]
        rows.sort(key=lambda r: ({"hidden": 0, "partial": 1, "full": 2}[r["level"]],
                                 r["count"], r["partition"]))
        return rows

    # --------------------------------------------------------- cross-check
    def cross_check(self) -> List[str]:
        """口径互推：只报数量级错（万元填成元、GMV 当营业收入、人数×1e4）。

        每条都是"两个独立来源的数对不上"。**单看任何一个都正确**，
        所以这类错必须靠互推抓。
        """
        # 结构问题**只在这里报一次**：load_problems 由 validate() 出口。
        # cross_check() 也接一份的话，industry_db.validate() 两次调用拼进同一个
        # 列表，同一条「scales 里有 1 项不是映射」会打两遍 —— 读的人会以为
        # 两个地方坏了，而去修一个不存在的第二处。
        problems: List[str] = []
        for p in self._partitions or []:
            pid = p.get("id", "")
            if not pid or pid not in self.entries:
                continue
            gdp = self.metric(pid, "gdp")
            profit = self.metric(pid, "profit")
            asset = self.metric(pid, "asset")
            val = self.metric(pid, "valuation")
            emp = self.metric(pid, "employment")

            # 1. 利润率：利润与产值同量级（两种口径都不是数量级的差别）
            if gdp and profit and gdp["cny"]:
                kind = gdp.get("kind", "")
                window = self.PROFIT_MARGIN_WINDOW.get(kind)
                if window:
                    margin = profit["cny"] / gdp["cny"]
                    if not (window[0] <= margin <= window[1]):
                        problems.append(
                            f"分区 {pid} 的 profit/gdp={margin:.2f}，超出 "
                            f"{kind} 口径的合理窗口 {window}"
                            f"（利润 {profit['cny']:,.0f} / 产值 {gdp['cny']:,.0f}；"
                            f"常见原因是单位错位或把流水当营业收入）")

            # 2. 人均产出：产值 / 人，抓"人数填成人数×1e4"
            if gdp and emp and emp.get("wan"):
                kind = gdp.get("kind", "")
                if kind in self.OUTPUT_PER_HEAD_KINDS:
                    heads = emp["wan"] * 1e4
                    per = gdp["cny"] / heads
                    lo, hi = self.OUTPUT_PER_HEAD_WINDOW
                    if not (lo <= per <= hi):
                        problems.append(
                            f"分区 {pid} 的人均产出 {per:,.0f} 元/人，超出窗口 "
                            f"[{lo:,.0f}, {hi:,.0f}]（产值 {gdp['cny']:,.0f} / "
                            f"{emp['wan']} 万人；常见原因是人数单位错或产值差 1e4）")

            # 3. 估值倍数：PE 与 PS 至少有一个落在正常区间
            if val and val.get("cny"):
                # 亏损行业（利润 ≤ 0）的 PE 没有意义：负利润算出来是负倍数，
                # 会被当成"倍数爆表"误报。按本模块立场——误报一次整条校验就会被
                # 当噪音关掉——所以利润不为正时直接跳过 PE。
                if profit and profit.get("cny") and profit["cny"] > 0:
                    pe = val["cny"] / profit["cny"]
                    if not (self.PE_WINDOW[0] <= pe <= self.PE_WINDOW[1]):
                        problems.append(
                            f"分区 {pid} 的 PE(估值/利润)={pe:.1f}，超出窗口 "
                            f"{self.PE_WINDOW}（估值 {val['cny']:,.0f} / "
                            f"利润 {profit['cny']:,.0f}）")
                if gdp and gdp.get("cny"):
                    ps = val["cny"] / gdp["cny"]
                    if not (self.PS_WINDOW[0] <= ps <= self.PS_WINDOW[1]):
                        problems.append(
                            f"分区 {pid} 的 PS(估值/产值)={ps:.2f}，超出窗口 "
                            f"{self.PS_WINDOW}（估值 {val['cny']:,.0f} / "
                            f"产值 {gdp['cny']:,.0f}）")

            # 4. 资产与利润：资产不能比利润还小三个数量级（那是把"元"写成"万元"）
            if asset and asset.get("cny") and profit and profit.get("cny") \
                    and asset["cny"] > 0 and profit["cny"] > 0:
                if asset["cny"] < profit["cny"] / 1e3:
                    problems.append(
                        f"分区 {pid} 的资产 {asset['cny']:,.0f} 不到利润 "
                        f"{profit['cny']:,.0f} 的千分之一（疑似资产口径漏了 1e3/1e4）")
        return problems

    def validate(self) -> List[str]:
        """口径账本自检：槽位语法、枚举、可见度必须有解释。"""
        problems: List[str] = add_all([], self.load_problems)
        # 数据源可用：文件缺失时 entries 为空，而"分区没落点"那条会逐分区报出来；
        # 但分区表也缺的话就无人可报，所以这里单独守一道。
        if not os.path.exists(self.path) and not self.entries:
            problems.append(
                f"未读到六口径规模账: {self.path}"
                f"（数据源缺失，自检不能视为通过）")
        known = {p.get("id") for p in (self._partitions or []) if p.get("id")}
        for pid, entry in self.entries.items():
            if pid not in known:
                problems.append(
                    f"规模账里的分区 {pid} 不是已知分区（悬空记录，永远查不到）")
            # missing 的键必须是真口径名：拼错（assett）时该格显示"未填原因"，
            # 而 validate 不报 —— "说不出总量又不说什么缺"正是这套账要守的一条。
            for key in (entry.get("_missing") or {}):
                if key not in SCALE_METRICS:
                    problems.append(
                        f"分区 {pid} 的 missing 键 {key!r} 不是口径名 "
                        f"{list(SCALE_METRICS)}（拼错会让该格静默变成「未填原因」）")
            for name in LEDGER_METRICS:
                cell = entry.get(name)
                if cell is None:
                    continue
                wrong = self.wrong_amount_key(cell, name)
                if wrong:
                    problems.append(
                        f"分区 {pid} 的 {name} 把金额写在了 {wrong!r} 键上"
                        f"（{name} 只认 {self.AMOUNT_KEY[name]!r}）——"
                        f"键写错会让这一格静默变空，而「没统计到」与「写错了」不是一回事")
                val = self._amount(cell, name)
                if val is None:
                    problems.append(
                        f"分区 {pid} 的 {name} 缺少 "
                        f"{self.AMOUNT_KEY[name]!r} 数值"
                        f"（空槽请整个省略，并在 missing 里写原因）")
                elif val < 0 and name != "profit":
                    problems.append(
                        f"分区 {pid} 的 {name}={val:,.0f} 为负"
                        f"（资产/估值/产值不可能为负，利润允许为负）")
                conf = cell.get("confidence")
                if conf is not None and conf not in CONFIDENCE:
                    problems.append(
                        f"分区 {pid} 的 {name}.confidence={conf!r} 不在 "
                        f"{list(CONFIDENCE)} 中")
                if name == "resource":
                    unit = cell.get("unit")
                    if unit not in RESOURCE_UNITS:
                        problems.append(
                            f"分区 {pid} 的 resource.unit={unit!r} 不在 "
                            f"{list(RESOURCE_UNITS)} 中（资源消耗是实物量，"
                            f"必须带单位，否则数字没有意义）")
        return problems


# 渲染留在 CLI（`cmd_industry_scale` / `cmd_industry_money`）：同一份表格写两遍，
# 迟早一边改了另一边没改，然后没人知道哪个是对的。engine 只出结构化数据。
