"""M11 资金流守恒账 · 钱的物质守恒（money_flow）

## 一句话

**每一笔钱都必须有另一头。** 大面上的总资金流向如果只列"某个行业产了多少值"，
一定会漏：钱从哪来、经谁的手、最后沉在哪里，一条链上任何一环没画，
汇总出来的"总额"就是假的，而且错得看不出来（每个数都对，加起来不对）。

## 三条不变式

1. **双边记账**：每条 flow 都是 `from → to`，同一笔钱在两端各记一次。
   所以「全局流入合计 = 全局流出合计」是恒等式，不是校验点——
   把它当校验点只会得到一句永远为真的绿灯。
2. **节点必须对账**：每个节点的流入/流出，要与外部权威口径（居民可支配收入、
   一般公共预算收入、固定资产投资…）对得上。对不上就是**漏画了流向**，
   差额超过容差即报。这是真正能抓漏的那一条。
3. **没有对账口径的节点，必须登记未观测流向**：既说不出总量、又不说缺什么，
   等于保证会漏，静默通过就是失守。`unobserved` 就是逼着把这句话写下来的字段。

## 为什么 `amount_cny` 允许为空

框架先立、数后补。路径已知但数额没查到时写 `null`，它仍然让整张图完整
（"这笔钱会走这条路"本身就是结论）；编一个数填上，比留空坏得多——
后面所有人都会拿它当真。这与 `gdp_cny: null` 是同一条规矩。

## 单位

全部用**元**（不是万元/亿元）。用元只有一个原因：口径混用是这类账最常见
的死法，而混用的信号就是数量级对不上——`amount_wan` 之类字段一多，
"这个数到底是万还是亿"就没人说得清了。
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional

import yaml

# 节点类型：部门（资金流量表的机构部门）+ 行业池（分区作为钱的容器）
NODE_TYPES = ("sector", "industry")
SECTORS = ("household", "enterprise", "government", "financial", "overseas")

# 资金流类型。别自由命名：类型是聚合的唯一维度，随手新增一个词，
# 按类型汇总时就会静默多出一行没人认识的钱。
FLOW_KINDS = {
    "wage": "劳动报酬（企业 → 居民）",
    "consumption": "消费支出（居民 → 行业池）",
    "procurement": "政府采购/公共支出（政府 → 行业池）",
    "transfer": "转移支付（政府 → 居民/企业）",
    "tax": "税收与社保（企业/居民 → 政府）",
    "saving": "储蓄（居民/企业 → 金融）",
    "credit": "信贷与融资（金融 → 行业池）",
    "interest": "利息与分红（行业池 → 金融）",
    "capex": "资本形成/投资（金融/企业 → 行业池）",
    "export": "出口收入（境外 → 行业池）",
    "import": "进口支付（行业池 → 境外）",
    "intermediate": "中间投入（行业池 → 行业池）",
    "allocation": "份额切分（部门总额 → 行业池，属分配而非交易）",
    "other": "其它（须在 note 说明）",
}
CONFIDENCE = ("high", "medium", "low")

# 节点对账容差：资金流量表与分项汇总本身就有口径差（约 3-8%），
# 定 10% 只抓"漏了一整条流向"，不抓统计口径的零头。
RECONCILE_TOLERANCE = 0.10


class MoneyFlowBook:
    """资金流守恒账：节点（部门/行业池）+ 双边 flows + 未观测登记 + 差额说明。"""

    def __init__(self, data_dir: Optional[str] = None,
                 partitions: Optional[List[dict]] = None):
        self.data_dir = data_dir or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "../../data")
        self.path = os.path.join(self.data_dir, "industry-money-flows.yaml")
        self.version = "0.1"
        self.updated_at = ""
        self.year_basis = ""
        self.nodes: List[dict] = []
        self.flows: List[dict] = []
        self.unobserved: List[dict] = []
        self.leaks: List[dict] = []
        # `pools` 必须在 __init__ 里就有：文件缺失时走降级路径，
        # 而任何访问 book.pools 的代码（导出、校验、测试）都会 AttributeError——
        # 降级路径本身不该比错误数据更脆。
        self.pools: List[dict] = []
        # 是否真读到了东西：`os.path.exists` 答不了这个问题 —— 文件在、内容却
        # 只有注释（一个空账）时它照样返回 True，于是"每条校验都没有违规"，
        # 自检全绿。缺文件和空账要分开报，而且都是硬失败。
        self.loaded = False
        # 先绑分区表再 _load：pools 段派生行业池节点时要用分区中文名
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
        self.year_basis = str(data.get("year_basis", ""))
        self.nodes = data.get("nodes", []) or []
        self.flows = data.get("flows", []) or []
        self.unobserved = data.get("unobserved", []) or []
        self.leaks = data.get("leaks", []) or []
        self.pools = data.get("pools", []) or []
        # 有 flows 或有 nodes 才算真读到账；只写了 version 注释的文件不算。
        self.loaded = bool(self.flows or self.nodes or self.pools)
        self._derive_pool_nodes()

    def _derive_pool_nodes(self) -> None:
        """pools 段 → 行业池节点（id = ``pool:<分区id>``）。

        为什么不让人手写一遍节点：同一个分区在 pools 里已经声明过"它是钱的一个
        容器"，再手抄一个 node 就是同一件事存两份，迟早对不上（而且错的那份
        不会报错，只会让钱流向一个不存在的节点）。
        """
        declared = {n.get("id") for n in self.nodes}
        for row in self.pools:
            pid = row.get("partition") or ""
            if not pid:
                continue
            nid = f"pool:{pid}"
            if nid in declared:
                continue
            self.nodes.append({"id": nid, "type": "industry", "partition": pid,
                               "name": self._pool_name(pid, row)})
            declared.add(nid)

    def _pool_name(self, pid: str, row: dict) -> str:
        for p in self._partitions or []:
            if p.get("id") == pid:
                return f"{p.get('name', pid)}（行业池）"
        return f"{pid}（行业池）"

    def bind(self, partitions: List[dict]) -> None:
        self._partitions = partitions
        # 分区名变了，行业池节点的显示名跟着变（节点 id 不变）
        for n in self.nodes:
            pid = n.get("partition")
            if pid:
                n["name"] = self._pool_name(pid, {})

    # ------------------------------------------------------------- lookups
    def node(self, node_id: str) -> Optional[dict]:
        for n in self.nodes:
            if n.get("id") == node_id:
                return n
        return None

    @staticmethod
    def gap_side(row: dict, kind: str) -> str:
        """money_gap 的 side 规范化：空串 → ``n/a``。

        导出与校验**必须共用这一个函数**：主键是 (node, kind, side)，而
        `unobserved` 的 side 恒空、`leaks` 不写 side 时也空 —— 不规范化的话
        库里会出现 side='' 的两条，SQLite 的非整数主键不去重 NULL/空串，
        validate 又只查节点存在性，于是"校验绿、导库撞 UNIQUE"。
        """
        if kind == "unobserved":
            return ""
        return (row.get("side") or "") or "n/a"

    def node_ids(self) -> List[str]:
        return [n.get("id", "") for n in self.nodes if n.get("id")]

    def flows_of(self, node_id: str) -> List[dict]:
        return [f for f in self.flows
                if f.get("from") == node_id or f.get("to") == node_id]

    @staticmethod
    def _num(value) -> Optional[float]:
        """金额取值：非数值一律当"没有数"，绝不让它参与加法。

        YAML 里 `amount_cny: 64e12` 会读成 float，但 `"64e12"`（带引号）是字符串；
        一条字符串混进去，`position()` / `totals()` 就在 `+=` 上抛 TypeError ——
        而这两个是 CLI 与导出都要走的路。数字不对是数据问题，不该变成崩溃。
        真正该报的是 validate()：它把"不是数值"明确报出来。
        """
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    def position(self, node_id: str) -> dict:
        """节点资金头寸：流入、流出、净额，以及"有多少条边数额待补"。

        `unknown` 是这套账最该露脸的数：一个节点净额看起来很平衡，
        但其中 8 条边没数额，那平衡毫无意义。所以它跟着数字一起给。
        """
        inflow = outflow = 0.0
        unknown = 0
        for f in self.flows_of(node_id):
            amt = self._num(f.get("amount_cny"))
            if amt is None:
                unknown += 1
                continue
            if f.get("to") == node_id:
                inflow += amt
            if f.get("from") == node_id:
                outflow += amt
        return {"inflow": inflow, "outflow": outflow,
                "net": inflow - outflow, "unknown_edges": unknown}

    def totals(self) -> dict:
        known = [v for v in (self._num(f.get("amount_cny"))
                             for f in self.flows) if v is not None]
        return {
            "nodes": len(self.nodes),
            "flows": len(self.flows),
            "flows_with_amount": len(known),
            "flows_without_amount": len(self.flows) - len(known),
            "gross_cny": sum(known),
            # 双边记账的恒等式：全局流入合计 ≡ 全局流出合计。
            # 放在这里是为了让读的人一眼看见它是恒等式，别当校验点。
            "double_entry_identity": True,
        }

    # --------------------------------------------------------- reconcile
    def reconcile(self) -> List[dict]:
        """逐节点与外部口径对账。有 `declared` 的节点才比，没声明的单列。

        差额 = 图里画出来的边求和 - 外部权威口径。差额大说明**漏画了流向**：
        这正是"大面上一定会漏"的那类错，只有对账才抓得住。
        """
        out: List[dict] = []
        for n in self.nodes:
            nid = n.get("id", "")
            pos = self.position(nid)
            for side, key in (("in", "inflow"), ("out", "outflow")):
                declared = self._num(n.get(f"declared_{side}_cny"))
                row = {"node": nid, "name": n.get("name", ""), "side": side,
                       "declared": declared, "traced": pos[key],
                       "unknown_edges": pos["unknown_edges"]}
                if declared is None:
                    row["gap"] = None
                    row["status"] = "no_declared"
                elif not declared:
                    row["gap"] = None
                    row["status"] = "declared_zero"
                else:
                    gap = pos[key] - declared
                    row["gap"] = gap
                    row["gap_ratio"] = abs(gap) / declared
                    row["status"] = ("ok" if abs(gap) / declared
                                     <= RECONCILE_TOLERANCE else "gap")
                out.append(row)
        return out

    def coverage_summary(self) -> dict:
        """这张账的可信度：多少节点有对账口径、多少资金流还没数额。"""
        rec = self.reconcile()
        declared = [r for r in rec if r["status"] in ("ok", "gap")]
        t = self.totals()
        return {
            "loaded": bool(self.loaded),
            "nodes": t["nodes"],
            "nodes_with_declared": len({r["node"] for r in declared}),
            "nodes_reconciled_ok": len({r["node"] for r in rec
                                        if r["status"] == "ok"}),
            "flows": t["flows"],
            "flows_with_amount": t["flows_with_amount"],
            "flows_without_amount": t["flows_without_amount"],
            "unobserved_entries": len(self.unobserved),
            "leaks": len(self.leaks),
            # 闭合度：有多少比例的边已经有数额。这不是"准确度"，
            # 是"这张图画完了多少"，两者不能混着说。
            "amount_coverage": (t["flows_with_amount"] / t["flows"]
                                if t["flows"] else 0.0),
        }

    # ------------------------------------------------------------ validate
    def validate(self) -> List[str]:
        """守恒账自检。每一条都对应一种"钱静默消失"的方式。"""
        problems: List[str] = []

        # 0. 数据源可用：文件缺失时节点为空，逐条校验都会"通过"——
        # 那正是本仓库第 13 条在防的「0 分区 0 职业还自检通过」。
        # 一张没有节点的守恒账不可能守恒任何东西，必须显式报出。
        if not os.path.exists(self.path):
            problems.append(
                f"未读到资金流守恒账: {self.path}"
                f"（数据源缺失，自检不能视为通过）")
        elif not self.loaded:
            problems.append(
                f"资金流守恒账是空账: {self.path}"
                f"（文件在但没有任何节点/资金流——空账不可能守恒任何东西）")
        elif not self.nodes:
            problems.append(
                f"资金流守恒账里没有任何节点: {self.path}"
                f"（空账不可能守恒任何东西）")

        ids = self.node_ids()

        # 1. 节点：id 唯一、类型合法、部门节点必须落在已知部门里
        seen: Dict[str, int] = {}
        for n in self.nodes:
            nid = n.get("id")
            if not nid:
                problems.append("资金流节点缺少 id（无法被任何 flow 引用）")
                continue
            seen[nid] = seen.get(nid, 0) + 1
            t = n.get("type")
            if t not in NODE_TYPES:
                problems.append(
                    f"节点 {nid} 的 type={t!r} 不在 {list(NODE_TYPES)} 中")
            if t == "sector" and n.get("sector") not in SECTORS:
                problems.append(
                    f"部门节点 {nid} 的 sector={n.get('sector')!r} 不在 "
                    f"{list(SECTORS)} 中（机构部门是资金流量表的口径，别自由命名）")
            if t == "industry" and self._partitions:
                pid = n.get("partition") or ""
                known = {p.get("id") for p in self._partitions if p.get("id")}
                if pid and pid not in known:
                    problems.append(
                        f"行业池节点 {nid} 指向不存在的分区 {pid}"
                        f"（悬空节点，产值永远对不上）")
        for nid, cnt in seen.items():
            if cnt > 1:
                problems.append(f"资金流节点 id 重复: {nid} 出现 {cnt} 次")

        # 2. 资金流：两端存在、类型合法、金额非负、同一笔不许记两遍
        edge_seen: Dict[tuple, int] = {}
        for f in self.flows:
            src, dst = f.get("from"), f.get("to")
            for label, val in (("from", src), ("to", dst)):
                if not val:
                    problems.append(f"资金流缺少 {label}（{f}）")
                elif val not in ids:
                    problems.append(
                        f"资金流的 {label}={val} 不是已知节点"
                        f"（钱流向了不存在的地方，等于凭空消失）")
            if src and dst and src == dst:
                problems.append(
                    f"资金流 {src} → {dst} 自流（同一节点进出，只会虚增总量）")
            kind = f.get("kind")
            if kind not in FLOW_KINDS:
                problems.append(
                    f"资金流 {src}→{dst} 的 kind={kind!r} 不在合法类型 "
                    f"{list(FLOW_KINDS)} 中（自由命名会让按类型汇总多出一行没人认的钱）")
            amt = f.get("amount_cny")
            if amt is not None:
                if isinstance(amt, bool) or not isinstance(amt, (int, float)):
                    problems.append(f"资金流 {src}→{dst} 的 amount_cny 不是数值")
                elif amt < 0:
                    problems.append(
                        f"资金流 {src}→{dst} 的 amount_cny={amt} 为负"
                        f"（方向由 from/to 表达，金额只写正数）")
            conf = f.get("confidence")
            if conf is not None and conf not in CONFIDENCE:
                problems.append(
                    f"资金流 {src}→{dst} 的 confidence={conf!r} 不在 "
                    f"{list(CONFIDENCE)} 中")
            key = (src, dst, kind)
            edge_seen[key] = edge_seen.get(key, 0) + 1
        for (src, dst, kind), cnt in edge_seen.items():
            if cnt > 1:
                problems.append(
                    f"资金流 {src}→{dst} ({kind}) 记了 {cnt} 次"
                    f"（同一笔钱记两遍，总量直接虚增；多条渠道请分开 kind）")

        # 3. 对账：有口径的必须对得上，差额超容差 = 漏画了流向
        for row in self.reconcile():
            if row["status"] != "gap":
                continue
            problems.append(
                f"节点 {row['node']} 的{('流入' if row['side'] == 'in' else '流出')}"
                f"对账差额 {row['gap']:,.0f} 元"
                f"（图中画了 {row['traced']:,.0f}，外部口径 {row['declared']:,.0f}，"
                f"偏差 {row['gap_ratio']:.1%} > {RECONCILE_TOLERANCE:.0%}）"
                f"—— 说明还有流向没画出来，或口径混用了")

        # 4. 没对账口径的节点必须登记未观测流向：否则"保证会漏"却静默通过
        declared_nodes = {r["node"] for r in self.reconcile()
                          if r["status"] in ("ok", "gap")}
        noted = {u.get("node") for u in self.unobserved if u.get("node")}
        for nid in ids:
            if nid in declared_nodes or nid in noted:
                continue
            problems.append(
                f"节点 {nid} 既没有 declared_in/out 对账口径，也没有在 unobserved "
                f"里登记未观测流向（说不出总量又不说什么缺 = 保证会漏）")

        # 5. 未观测登记必须指向真实节点，且要写清缺什么
        for u in self.unobserved:
            if u.get("node") not in ids:
                problems.append(
                    f"unobserved 登记的节点 {u.get('node')} 不存在")
            if not (u.get("missing") or u.get("reason")):
                problems.append(
                    f"unobserved 里节点 {u.get('node')} 没写缺什么"
                    f"（没有说明就等于没有登记）")

        # 4-b. gap 业务主键唯一：库里 money_gap 的主键是 (node, kind, side)，
        # 而 unobserved 的 side 恒为空串、leaks 不写 side 时也是空串。
        # 同一节点登记第二条未观测、或同一节点同一侧记两笔差额时，
        # validate 早先返回 []（只查节点存在性与原因非空），
        # 而 data_sql 会生成两条撞主键的 INSERT → IntegrityError。
        # 「同一笔钱记两遍」在 flow 上是明确拦的，gap 上不能漏。
        gap_keys: Dict[tuple, int] = {}
        for u in self.unobserved:
            key = (u.get("node", ""), "unobserved", self.gap_side(u, "unobserved"))
            gap_keys[key] = gap_keys.get(key, 0) + 1
        for lk in self.leaks:
            key = (lk.get("node", ""), "gap", self.gap_side(lk, "gap"))
            gap_keys[key] = gap_keys.get(key, 0) + 1
        for (node, kind, side), cnt in gap_keys.items():
            if cnt > 1:
                where = f"{kind}" + (f"/{side}" if side else "")
                problems.append(
                    f"节点 {node} 的 {where} 登记了 {cnt} 次"
                    f"（money_gap 主键是 (node, kind, side)，"
                    f"重复会在导入时报 UNIQUE 冲突；多条原因请合并成一条写清）")

        # 6. 差额说明（leaks）必须指向真实节点并给出原因：
        #    允许有已知差额，但不允许"差额存在且没人解释"
        for lk in self.leaks:
            if lk.get("node") not in ids:
                problems.append(f"leaks 里的节点 {lk.get('node')} 不存在")
            if not lk.get("reason"):
                problems.append(
                    f"leaks 里节点 {lk.get('node')} 的差额没写原因"
                    f"（有差额可以，不解释不行）")
            amt = lk.get("amount_cny")
            if amt is not None and (isinstance(amt, bool)
                                    or not isinstance(amt, (int, float))):
                problems.append(
                    f"leaks 里节点 {lk.get('node')} 的 amount_cny 不是数值")
        return problems

    # ------------------------------------------------------------- render
    def render_text(self) -> str:
        t = self.totals()
        s = self.coverage_summary()
        lines = ["=" * 78,
                 f"资金流守恒账  v{self.version}  口径年份 {self.year_basis or '-'}",
                 "-" * 78,
                 f"节点 {t['nodes']} 个（部门 + 行业池）  资金流 {t['flows']} 条："
                 f"已填数额 {t['flows_with_amount']} 条 / 待补 "
                 f"{t['flows_without_amount']} 条（图完整度 {s['amount_coverage']:.0%}）",
                 f"对账口径: {s['nodes_with_declared']} 个节点有外部总量可比，"
                 f"其中对得上 {s['nodes_reconciled_ok']} 个；"
                 f"未观测登记 {s['unobserved_entries']} 条，已知差额 {s['leaks']} 条",
                 "不变式: 双边记账 → 全局流入 ≡ 全局流出（恒等式）；"
                 "能抓漏的是**节点与外部口径对账**，不是这个恒等式",
                 "-" * 78]
        rec = {(r["node"], r["side"]): r for r in self.reconcile()}
        # 表头也必须走 _cell：f-string 的 '<22' 按**字符数**补，中文一个字占两列，
        # '节点' 补到 22 字符 = 44 显示列，比表体的 22 列宽出 22 列，整行错位。
        lines.append(_cell("节点", 22) + _right("流入(亿)", 14)
                     + _right("流出(亿)", 14) + _right("净额(亿)", 14)
                     + "  " + _cell("对账", 20) + _right("待补边", 8))
        for n in self.nodes:
            nid = n.get("id", "")
            pos = self.position(nid)
            flags = []
            for side in ("in", "out"):
                r = rec.get((nid, side)) or {}
                if r.get("status") == "ok":
                    flags.append(f"{side}:✓")
                elif r.get("status") == "gap":
                    flags.append(f"{side}:Δ{r['gap_ratio']:.0%}")
                elif r.get("status") == "no_declared":
                    flags.append(f"{side}:未声明")
            lines.append(_cell(n.get("name", nid), 22)
                         + _right(f"{pos['inflow'] / 1e8:,.0f}", 14)
                         + _right(f"{pos['outflow'] / 1e8:,.0f}", 14)
                         + _right(f"{pos['net'] / 1e8:,.0f}", 14) + "  "
                         + _cell("/".join(flags) or "-", 20)
                         + _right(pos["unknown_edges"], 8))
        lines.append("-" * 78)
        lines.append("资金流明细（`null` = 路径已知、数额待补，不是 0）：")
        for f in self.flows:
            amt = f.get("amount_cny")
            lines.append(
                f"  {_cell(f.get('from', '?'), 22)}→ {_cell(f.get('to', '?'), 22)}"
                f"{_cell(f.get('kind', ''), 14)}"
                f"{(f'{amt / 1e8:,.0f} 亿' if amt is not None else '待补'):>14}"
                f"  {f.get('confidence', '-')}")
        if self.leaks:
            lines.append("-" * 78)
            lines.append("已知差额（有差额可以，不解释不行）：")
            for lk in self.leaks:
                amt = lk.get("amount_cny")
                lines.append(f"  {_cell(lk.get('node', ''), 22)}"
                             f"{(f'{amt / 1e8:,.0f} 亿' if amt is not None else '-'):>14}"
                             f"  {lk.get('reason', '')}")
        lines.append("=" * 78)
        return "\n".join(lines)


def _disp_width(text: str) -> int:
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
               for ch in str(text))


def _cell(text, width: int) -> str:
    """左对齐：width 是**显示宽度**（中文一字两列）。"""
    text = str(text)
    return text + " " * max(0, width - _disp_width(text))


def _right(text, width: int) -> str:
    """右对齐（数字列）：同样按显示宽度补，不用 f-string 的 '>14'。"""
    text = str(text)
    return " " * max(0, width - _disp_width(text)) + text
