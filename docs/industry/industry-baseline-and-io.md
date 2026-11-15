# 官方口径逐年对表 + 投入产出生产法

两本账回答的是两个不同的问题，缺任一本，「可对外引用」都是空话：

| 账 | 问题 | 数据文件 | 引擎 |
|---|---|---|---|
| 官方口径基准 | **这个数有没有出处？** | `data/industry-official-baseline.yaml` | `OfficialBaseline` |
| 投入产出账 | **这个数会不会重复计？** | `data/industry-input-output.yaml` | `InputOutputBook` |

---

## 一、逐年对表：`high` 不能再自己写

### 三种关系

| relation | 含义 | 比什么 |
|---|---|---|
| `equal` | 分区范围 = 官方范围 | 偏差 `\|分区−官方\|/官方 ≤ tolerance`（默认 10%） |
| `envelope` | 分区 ⊆ 官方（官方是门类总量） | 上界 `分区 ≤ 官方×(1+tolerance)` |
| `incomparable` | 口径不同，**不能相减** | 只登记关系 + 必须写 `reason`，不做数值比较 |

`incomparable` 不是免责出口：**该分区不得标 `high`**。软件业务收入必然大于
信息服务业增加值，相减得到的差额没有经济含义，写清楚比装作能比更有用。

### 年份怎么定

```
part_year(part) -> (year, source)
  1. gdp_year           → ("declared")      显式钉死
  2. gdp_year_basis     → ("basis_range")   区间里取**基准已有**的末年
  3. 都没有             → (None, "")
```

第 2 条的「基准已有」是关键：区间写 2023-2024、基准只录到 2023 时取 2023。
硬取 2024 会得到「官方没这一年的数」，看起来像对不上，其实只是基准还没录。
`year_source` 一路带到对表结论里，推出来的年份不会被当成声明过的。

### `origin`：来历比数值更重要

每个基准必须写自己是**怎么来的**：

| origin | 含义 | 能否背书 `high` |
|---|---|---|
| `published` | 逐表抄自公开统计表（年鉴/公报原值） | ✅ 唯一可以的一档 |
| `recalled` | 凭公开量级回忆写的，未逐表核对 | ❌ 数值可能对，但没有可追溯的表页 |
| `backfilled` | 由分区现有估算**反推**的"官方值" | ❌ 最危险 |

`backfilled` 为什么最危险：它让对表变成循环论证 —— 自己和自己比，永远 0.00% 偏差，
得出的"对上"什么也没证明，却看起来像证据。**两个独立来源对得上才叫交叉验证；
把 A 抄成 B 再比一次，得到的是一致地错，不是一致地对。**

这条规矩上线就抓出 4 个假 `high`：制造业、采矿业、电力热力燃气水、卫生总费用，
它们的基准全是按占比反算的，于是 `industry check` 报
「基准 origin='backfilled' 不是逐表抄来的公开值，比出来的一致什么也没证明」，
4 个分区一起降为 `medium`。

现在全仓只剩 4 个 `high`，都有逐表抄来的公报值背书：
电子商务（网上零售额）、餐饮美食（餐饮收入）、建筑工程（建筑业总产值）、
农林牧渔（第一产业增加值）。

### 置信度是算出来的

```
status == ok 且 origin == published  → high
status == ok 但 origin != published  → medium   （一致什么也没证明）
incomparable / no_series             → medium
unlinked                             → low
gap                                  → low
```

`baseline.confidence_of(pid)` 给机器判定的上限，`partition.gdp_confidence` 是标注值。
标注高于上限 → 第 24 条校验报「high 只能由通过的对表背书」。

### 命令

```bash
python3 src/hanghang/cli/main.py industry baseline                     # 全景
python3 src/hanghang/cli/main.py industry baseline --partition manufacturing
python3 src/hanghang/cli/main.py industry baseline --benchmarks        # 基准表 + 同比
python3 src/hanghang/cli/main.py industry baseline --only gap          # 只看超容差的
```

---

## 二、生产法：切分的去重规则

```
总产出 = 增加值 + 中间投入
```

三端来自三个独立来源：总产出看行业统计（总产值/营业收入/GMV），增加值看国民经济
核算，中间投入由投入产出表或相减得出（标 `derived: true`）。两边对不上，说明其中
一个是别的口径。

### 切分锚点只有两条合法路径

部门层总额是**增加值性质**（收入法 GDP）。分区手里的数常常不是：

| 分区 | 数 | 为什么不能直接切 |
|---|---|---|
| 电商 | 15 万亿 GMV | 平台两头各计价一次 |
| 软件研发 | 6 万亿 软件业务收入 | 含中间投入与硬件 |
| 建筑 | 31.6 万亿 总产值 | 含分包重复报量 |

所以：

1. 分区本来就是 `value_added` 口径 → 直接可切
2. output/revenue/GMV → 必须先有 `va_ratio`（增加值 ÷ 总产出）折算

**没有 `va_ratio` 就不许切**，宁可 `null`。也不许用行业平均值兜底 ——
平均增加值率套到具体行业上，得到的是一个看起来合理的错数。

### 三处不得重复计（第 25 条校验）

1. 中间投入构成合计 = 中间投入总额（声明 `complete` 时）
2. 某分区作为投入方出现在别人 `inputs` 里的合计 ≤ 它自己的总产出
3. 所有分区增加值合计 ≤ 全国 GDP（分母从 `gdp-total` 基准借，不抄第二份）

### 命令

```bash
python3 src/hanghang/cli/main.py industry io                            # 三端全景
python3 src/hanghang/cli/main.py industry io --partition construction-eng
python3 src/hanghang/cli/main.py industry io --pools                    # 哪些池能切
```

---

## 三、`memo`：摊开看 ≠ 新发生一笔钱

这是接锚点时一定会撞上的坑，单独讲：

```
sector-enterprise → pool:manufacturing  allocation  33.0 万亿
```

制造业 33 万亿增加值**本就含在**企业部门那 110.5 万亿里。如果把这条 `allocation`
计入企业部门的流出，流出立刻变 143.5 万亿，对账偏差 30% 爆红 ——
而两条记录各自都是对的。**同一个数记两遍，总计就假了。**

所以：

- `allocation` 一律 `memo: true`，validate 强制（反向也报：把 `wage` 标成 memo
  会静默漏掉一笔真钱）
- memo 边不进 `position()` 的流入/流出，单独计 `memo_edges`
- `amount_coverage` 分母只算真实流 —— 否则「图画完了多少」永远上不去
- 落库到 `money_flow.memo`，扁平表也带这列：`SUM(amount_cny) WHERE memo=0`

---

## 四、落库

```sql
baseline_series (benchmark, year) PK   -- 官方表值逐年存
baseline_link   (partition) PK         -- 对表关系 + 结论（ok/gap/incomparable/…）
io_account      (partition) PK         -- 生产法三端 + va_ratio + 池可行性
money_flow.memo                        -- 新增列：摊开看 vs 真钱
```

`schema_version` 1.3.0，12 张表。导出新增 `baseline-check.csv` / `io-accounts.csv`。
