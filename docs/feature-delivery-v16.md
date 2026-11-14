# v16 · 六口径规模账 + 资金流守恒账

> Issue #30 说：「得有个数据交叉验证的机制，大面上的总资金流动情况，就和物质守恒一样，
> 哪里移动到哪里，不然肯定会漏，甚至大面上的数据也会遗漏。另外行业较大之后是不会不可见的，
> 按盈利规模、资产规模、估值规模、从业人数、资源消耗，不同口径下一般不会完全隐身。」
>
> 这一轮加的就是这两件事：**一张能对账的资金流表** + **一套让行业不会隐身的六口径落点**。
> 不加新机制、不改已有字段语义，只把「漏」这件事变成能被机器抓住的东西。

## 一、六口径：行业不该因为产值没统计就整体隐身

产值（增加值）是最难拿的一格。全国只有约 20 个门类有官方增加值，细分行业往往没有
独立统计。但同一个行业在别处留着痕迹——利润总额、资产总计、上市板块市值、从业人数、
能耗水耗。**只要任一口径有数，这个行业就还在表里。**

口径不是「更精确的同一个数」，而是同一批钱的六个侧面：

| 口径 | 回答什么 | 存在哪 | 数量 |
|---|---|---|---|
| `gdp` | 一年新增多少价值 | `partition.gdp_cny` + `gdp_kind`（单一来源，不重复存） | 35/41 |
| `employment` | 多少人在干 | `partition.employment`（单一来源） | 37/41 |
| `profit` | 兜里剩下多少 | `industry-scales.yaml` | 36/41 |
| `asset` | 压着多少钱 | 同上 | 13/41 |
| `valuation` | 市场给多少钱 | 同上 | 7/41 |
| `resource` | 吃掉多少实物 | 同上（保留实物单位，不折成钱） | 14/41 |

```
看清大半(≥4 格)  19 个分区
至少一面可见      22 个分区
六格全空           0 个分区
```

**0 个全空**是这一轮的验收线。`admin-office`（行政办公）只有就业一格——它就是企业的
内部职能，没有独立产值/利润/资产/估值，这不是缺数据，是行业特征。这句话写在
`missing` 里，可被 `validate` 检查，而不是留在某个人的记忆里。

### 为什么摊成「行」而不是「列」

`scale_metric` 表一行一个（分区，口径），缺的口径**也占一行**，`missing_reason`
里是那句「为什么这一格是空的」。

摊成宽表（每个口径一列）的话，「六个口径全空」就是六个 NULL，和「这个分区根本
没登记」长得一模一样——**隐身这件事在库里就看不见了**。而这一轮要防的恰恰就是隐身。

### 交叉验证：只抓数量级错

四个互推，全部是「两个独立来源的数对不上」：

| 互推 | 抓什么 |
|---|---|
| 利润 ÷ 产值 | 单位错位、把 GMV 当营业收入 |
| 产值 ÷ 从业人数 | 人数单位差 1e4（写成"人"而不是"万人"） |
| 估值 ÷ 利润（PE）、估值 ÷ 产值（PS） | 估值口径混了亿元/万元 |
| 资产 ÷ 利润 | 资产漏了 1e3/1e4 |

窗口开得很宽（人均产出 1 万 ~ 5 亿、PE 0.5 ~ 500），**宁可漏报，不可误报**——
误报一次，整条校验就会被当成噪音关掉，那才是真的失守。

真实数据现在 0 报错；补数时改错一个量级，立刻红。

## 二、资金流守恒：钱不会凭空生灭

### 三条不变式

1. **双边记账**。每条 flow 都是 `from → to`，同一笔钱两端各记一次。
   所以「全局流入合计 = 全局流出合计」是**恒等式**。
2. **节点与外部口径对账**。这才是能抓漏的一条：图里画出来的边求和，必须对得上
   居民可支配收入、一般公共预算收入这类权威总量。偏差超 10%（资金流量表与分项
   汇总的固有口径差）即报「还有流向没画出来」。
3. **没有对账口径，就必须登记未观测流向**。说不出总量、又不说什么缺，等于保证会漏，
   而它会静默通过。`unobserved` 就是逼着把这句话写下来的字段。

> 第 1 条刻意**不做成校验点**。把恒等式当校验点，得到的是一句永远为真的绿灯——
> 看着很安心，实际什么都没守住。真正会红的是第 2 条。

### 现在画到哪

```
节点 13 个（5 个机构部门 + 8 个行业池）
资金流 27 条：已填数额 19 条 / 待补 8 条（图完整度 70%）
对账：5 个部门全部闭合（居民 80.8 万亿 / 企业 110.5 万亿 / 政府 25.7 万亿
      / 金融 42.2 万亿 / 境外 24.2 万亿，2023-2024 量级估算）
```

```
sector-enterprise → sector-household   wage         64.0 万亿   劳动报酬
sector-household  → sector-enterprise  consumption  47.0 万亿   居民消费
sector-enterprise → sector-government  tax          19.7 万亿   企业税负
sector-government → sector-household   transfer     10.0 万亿   社保待遇/补贴
sector-government → sector-enterprise  capex        10.5 万亿   政府主导资本形成
sector-financial  → sector-enterprise  credit       26.2 万亿   企业新增融资
sector-overseas   → sector-enterprise  export       23.8 万亿   出口收入
sector-enterprise → pool:manufacturing allocation   待补        份额切分（规则未定）
```

### 为什么允许 `amount_cny: null`

框架先立、数后补。8 个行业池的份额切分规则还没定（制造业 33 万亿增加值摊到
40 万个规上企业再切到分区，要先定中间投入和重复计价的处理），所以数额留空。

**留空的边照样有意义**：它把「这个行业的钱从哪来」钉死，补数时不用重新想路径。
编一个数填上，比留空坏得多——后面所有人都会拿它当真。这与 `gdp_cny: null`
是同一条规矩。

### 已知差额写在 `leaks` 里，并解释清楚

- 政府性基金预算与国有土地出让收入 **8.6 万亿**未并入一般公共预算口径。
  补的时候**不要直接加进 `tax` 边**：它对应企业部门的资产性支出，与
  `procurement`/`capex` 会重复计价，必须单独开一条边并同步修企业部门的流出，
  否则两个部门一起虚增。
- 影子银行（信托/租赁/保理）与表外理财往来 **3.5 万亿**未纳入本账。
  这部分在资金流量表里被单列，并入前要先确认不会与 `credit` 边重复。

有差额可以，不解释不行——`validate` 第 23 条会拦住「有差额且没写原因」。

## 三、落到库表

表结构从 5 张扩到 9 张（`schema_version` 1.0.0 → 1.1.0）：

| 表 | 内容 |
|---|---|
| `scale_metric` | 六口径，一行一个（分区，口径），缺口也占行 |
| `money_node` | 资金流节点：`declared_in/out_cny` 是对账口径 |
| `money_flow` | 资金流：`from`/`dst`/`kind`/`amount_cny`，金额全用元 |
| `money_gap` | 对账差额（`gap`）与未观测登记（`unobserved`） |

**行业池节点由 `pools` 段派生**（id = `pool:<分区id>`），不手写：同一个分区在
`pools` 里已经声明过「它是钱的一个容器」，再抄一遍就是同一件事存两份；而错的那份
不会报错，只会让钱流向一个不存在的节点。

导出从 7 份变 10 份：新增 `scales.csv` / `money-nodes.csv` / `money-flows.csv`。
`money-nodes.csv` 里直接带 `inflow_cny` / `outflow_cny` / `net_cny` / `in_gap_ratio`，
BI 侧一句 SQL 就能查「哪个节点的流入对不上」。

## 四、校验：20 条 → 23 条

| # | 校验点 |
|---|---|
| 21 | 六口径槽位合法 + **每个分区必须有落点**：漏一个就是整体隐身，而覆盖率不会变红半格 |
| 22 | 六口径互推 + 全空分区必须逐格解释 |
| 23 | 资金流守恒账：节点/边/对账/未观测登记四关 |

条数仍只有一处来源（`VALIDATE_CHECK_COUNT`），README / 文档表格 / CLI 回执读它。

## 五、命令

```bash
# 六口径：谁有数谁说话
python3 src/hanghang/cli/main.py industry scale
python3 src/hanghang/cli/main.py industry scale --partition manufacturing
python3 src/hanghang/cli/main.py industry scale --gaps      # 全空分区 + 逐格原因

# 资金流：钱从哪来、经谁的手、沉在哪里
python3 src/hanghang/cli/main.py industry money
python3 src/hanghang/cli/main.py industry money --node sector-household
python3 src/hanghang/cli/main.py industry money --kinds
```

## 六、验证

- 36 个测试文件全通过（新增 `tests/test_scale_money_m11.py`）
- `industry check` 23 条校验 41 分区 / 178 职业，双向对齐无缺口，退出码 0
- `export_industry_db.py --check` 导入往返 9 表 / 2344 行一致
- 其余产物校验全绿（rolecards / role chain / class db / role db）

## 七、评审返工（PR #34 首轮）

首轮评审给了 10 条，逐条核实**全部成立**，两条是 P0：

| # | 问题 | 为什么测试跑不到 | 修法 |
|---|---|---|---|
| 1 | `profit` 手滑写成 `{wan: ...}` → `cross_check` KeyError → `industry check` traceback | 数据正常时永远不触发；而**校验器自己挂了**是最难查的故障——红灯既不是"数据坏了"也不是"绿" | `ScaleLedger.AMOUNT_KEY`：每个口径只认自己那一个键（`wan` 是就业的、`value` 是资源的），写错键单独报"金额写在了错误的键上" |
| 2 | `gdp_cny INTEGER` 存 33 万亿 → PostgreSQL 建不出库 | SQLite 不做数字类型强校验，导入往返自检全绿；**这个错只有真进 PG 才露** | `_TYPES` 加 `bigint` 档，金额列一律 BIGINT。补断言「PG DDL 里承载金额的列不得是 INTEGER」 |
| 3 | `.cnb.yml` 注释写 `data/industry-db/*.sql`，实际在 `data/db/industry/` | 注释不参与执行 | 改正 |
| 4 | `money_gap` 主键 `(node, kind, side)`，`unobserved` 的 `side` 恒空 → 重复登记时 validate 绿、导库撞 UNIQUE | validate 只查节点存在性与原因非空，不查重复 | 补 `(node, kind, side)` 唯一性检查 |
| 5 | `MoneyFlowBook.pools` 未在 `__init__` 初始化 | 只在文件缺失的降级路径上炸，而这条路径上一轮刚加 | `__init__` 里就赋空列表 |
| 6 | `_col_sql` 两个分支都返回空串 → DDL 里 `NOT NULL` 计数为 0 | 不报错，只是**契约不成立**：`money_gap.reason` 可为 NULL，而 validate 要求"有差额不解释不行" | `" NOT NULL" if notnull else ""` |
| 7 | `missing` 键名拼错（`assett`）→ 该格显示"未填原因"，validate 不报 | 正是"说不出总量又不说什么缺"这条被绕过 | 校验 `_missing` 的键 ⊆ `SCALE_METRICS` |
| 8 | 亏损行业的 PE 是负倍数，被当成"倍数爆表"误报 | 现有数据里没有负利润，潜伏 | PE 只在 `profit > 0` 时判 |
| 9 | `ScaleLedger.render_text` 死代码，CLI 另写一份同样逻辑 | — | 删掉，engine 只出结构化数据；顺带修 `... or "-"` 的无效兜底 |
| 10 | 文档写"30 项"，实际 33 项 | 手抄数字 | 不再写死条数 |

评审第 8 条那句话我照抄了一遍：**误报一次，整条校验就会被当成噪音关掉**。
所以这轮所有修复都遵守同一条：宁可漏报，不可误报；宁可报"写错了"，不可静默变空。

返工新增 10 项回归用例（共 43 项），全部瞄准"已想到的路之外的路径"。

## 八、还没做的（下轮）

1. **行业池份额切分的规则**。8 个池的流入数额全待补，卡在「中间投入怎么去重」
   这个口径问题上——不是拿不到数，是拿了会重复计。
2. **逐年对齐**。`year_basis` 现在统一写 `2023-2024`，是量级估算。
   要对到官方表值，`confidence` 才配从 `low/medium` 升到 `high`。
3. **行业池与部门层的中间投入**。`intermediate` 类型留了，但行业池之间的
   投入产出关系还没画——这张表真正闭合要靠投入产出表。
