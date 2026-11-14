# 六口径规模账 + 资金流守恒账

> 两份数据文件，回答两个「漏」的问题：
> `data/industry-scales.yaml` —— 行业会不会因为某个口径没数就整体隐身？
> `data/industry-money-flows.yaml` —— 大面上的钱会不会漏掉某一段？

## 一、六口径：一个行业有六个侧面

产值（增加值）是最难拿的一格。全国只有约 20 个门类有官方增加值，细分行业往往
没有独立统计。但同一个行业在别处留着痕迹。

| 口径 | 回答什么 | 单位 | 存在哪 |
|---|---|---|---|
| `gdp` | 一年新增多少价值 | 元（+`gdp_kind` 口径类型） | `partition.gdp_cny` |
| `employment` | 多少人在干 | 万人 | `partition.employment` |
| `profit` | 兜里剩下多少 | 元 | `industry-scales.yaml` |
| `asset` | 压着多少钱 | 元 | 同上 |
| `valuation` | 市场给多少钱 | 元 | 同上 |
| `resource` | 吃掉多少实物 | **实物单位** | 同上 |

`gdp` / `employment` 不在这份文件里重复存，一律从 `partition` 现读。同一件事存两份，
迟早对不上，而且没人知道哪份是对的。

### 可见度分级

| 等级 | 命中口径数 | 含义 |
|---|---|---|
| `full` | ≥4 | 六个侧面看清了大半，可以跨行业比 |
| `partial` | 1-3 | 至少没隐身，能排序能定位，缺口写着 |
| `hidden` | 0 | **必须逐格说明为什么**（没有独立口径 / 并入别的分区统计） |

当前 41 个分区：`full` 19 / `partial` 22 / `hidden` 0。

### `missing` 是数据，不是备注

```yaml
- partition: admin-office
  missing:
    profit: 企业内部职能，无独立利润口径（成本计入各自主业）
    asset: 同上，资产属各自主业
    valuation: 无独立主体
    resource: 办公耗能未按职能拆分
```

「没有独立口径」本身就是这个行业的结论，所以它跟有数的口径一样要被写下来、
被校验。「说不出总量又不说什么缺」= 保证会漏，`validate` 第 22 条直接报。

`gdp` / `employment` 的缺失原因会自动回落到 `partition.gdp_scope` /
`employment_source`——那两句话本来写的就是同一件事，再抄一遍只会一边改一边没改。

### 资源消耗保留实物单位

```
tce（吨标煤）/ kwh / gwh / ton / ton_water / m3
```

不折成人民币。折成钱要选电价/煤价，一选就把一件实测的事变成一件估算的事。
`manufacturing` 的 26.0 亿吨标煤是实测口径，折成"约 2 万亿"就什么都没说。

### 交叉验证窗口

| 互推 | 窗口 | 抓什么 |
|---|---|---|
| `profit / gdp` | 按 `gdp_kind` 分档（增加值 -0.6~1.2，营收类 -0.8~0.9） | 单位错位、GMV 当营业收入 |
| `gdp / (employment×1e4)` | 1 万 ~ 5 亿 元/人 | 人数单位差 1e4 |
| `valuation / profit`（PE） | 0.5 ~ 500 | 估值口径混了亿元/万元 |
| `valuation / gdp`（PS） | 0.01 ~ 200 | 同上 |
| `asset / profit` | 不低于 1/1000 | 资产漏了 1e3/1e4 |

窗口开得宽，**宁可漏报，不可误报**：误报一次，整条校验就会被当成噪音关掉。

## 二、资金流：双边记账 + 节点对账

### 三条不变式

1. **双边记账**。每条 flow 是 `from → to`，同一笔钱两端各记一次。
   → 「全局流入 ≡ 全局流出」是**恒等式**，不是校验点。
2. **节点对账**。图里画出来的边求和 vs 外部权威总量，偏差 >10% 即报
   「还有流向没画出来」。**这是唯一能抓漏的一条。**
3. **未观测登记**。没有对账口径的节点，必须在 `unobserved` 写清缺什么、为什么缺、
   怎么补。说不出总量又不说什么缺 = 保证会漏，而它会静默通过。

### 十三个节点

```
sector-household / enterprise / government / financial / overseas   五个机构部门
pool:<分区id>                                                      行业池（由 pools 段派生）
```

行业池不手写节点：同一个分区在 `pools` 里声明过「它是钱的一个容器」，
再抄一遍就是同一件事存两份；错的那份不报错，只会让钱流向不存在的节点。

### `amount_cny: null` 不是 0

路径已知、数额待补时写 `null`。它照样让整张图完整（「这笔钱会走这条路」
本身就是结论），补数时不用重新想路径。编一个数填上比留空坏得多。

当前 27 条边里 8 条待补（都是行业池的份额切分，卡在中间投入去重规则上）。

### `leaks`：有差额可以，不解释不行

已知差额两条，写在文件里并解释：

- 政府性基金 + 土地出让收入 8.6 万亿未并入一般公共预算口径。
  补时**不要直接加进 `tax` 边**——它对应企业部门的资产性支出，
  与 `procurement`/`capex` 重复计价，必须单独开边并同步修企业部门流出。
- 影子银行表外往来 3.5 万亿未纳入。并入前要先确认不与 `credit` 边重复。

## 三、表结构

```
scale_metric   (partition, metric) PK  —— 一行一个口径，缺的也占一行
money_node     (id) PK                —— declared_in/out_cny 是对账口径
money_flow     (src, dst, kind) PK    —— 金额全用元
money_gap      (node, kind, side) PK  —— gap（已知差额）/ unobserved（未观测）
```

金额全部用**元**，不是万元/亿元。口径混用是这类账最常见的死法，
而混用的信号就是数量级对不上；`amount_wan` 之类字段一多，
「这个数是万还是亿」就没人说得清了。

## 四、校验（21-23 条）

| # | 守什么 |
|---|---|
| 21 | 槽位语法/枚举合法、分区不悬空、**每个分区都要有落点** |
| 22 | 六口径互推 + 全空分区必须逐格解释 |
| 23 | 节点/边/对账/未观测登记四关 |

## 五、命令

```bash
python3 src/hanghang/cli/main.py industry scale
python3 src/hanghang/cli/main.py industry scale --partition manufacturing
python3 src/hanghang/cli/main.py industry scale --gaps
python3 src/hanghang/cli/main.py industry money
python3 src/hanghang/cli/main.py industry money --node sector-government
python3 src/hanghang/cli/main.py industry money --kinds
```
