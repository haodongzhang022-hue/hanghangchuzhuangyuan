# 行业分区库 · 可导入产物（准备进库）

> 回答一个问题：**客户买好服务器了，怎么把这套数据装进去。**
> 结论：拿到 3 个 SQL 文件直接跑，不需要 Python，也不需要人工把 SQLite 语法改写成 PG。

## 1. 产物清单

| 文件 | 谁写的 | 进版本库 | 用途 |
|---|---|---|---|
| `data/*.yaml` | 人手写 | ✅ | **权威源**。可评审、可回滚、可被知识库切片 |
| `data/db/industry/00-schema.sqlite.sql` | `scripts/export_industry_db.py` | ✅ | SQLite 建表 |
| `data/db/industry/00-schema.postgresql.sql` | 同上 | ✅ | PostgreSQL 建表（同表同列） |
| `out/industry-db/10-data.sql` | `industry export` | ❌ | 数据（与方言无关，两边都能跑） |
| `out/industry-db/*.csv` / `.json` / `.sqlite` | 同上 | ❌ | 给 BI / 知识库 / 本地查表直接吃（含 `scales.csv` / `money-nodes.csv` / `money-flows.csv`） |

**结构进库、数据不进库**：结构是契约，改一列要评审、要能被下游看见；数据可从 yaml
秒级重建，把 1.6 MB 生成 SQL 提交进 git 只会得到看不见的 diff，改一次数据冲突一次。

```bash
# 交付前生成全套
python3 src/hanghang/cli/main.py industry export --out out/industry-db
# 或直接建一份能打开的库
python3 scripts/export_industry_db.py --sqlite /tmp/hanghang-industry.db
```

## 2. 导入（三种目标库）

```bash
# SQLite
sqlite3 hanghang.db < data/db/industry/00-schema.sqlite.sql
sqlite3 hanghang.db < out/industry-db/10-data.sql

# PostgreSQL
psql -d hanghang -f data/db/industry/00-schema.postgresql.sql
psql -d hanghang -f out/industry-db/10-data.sql
```

数据 SQL 刻意只用**标准写法**：不写 `AUTOINCREMENT`、不用反斜杠转义单引号
（那是 MySQL 扩展，SQLite 与 PG 都不认）、不依赖 `PRAGMA`。所以一份数据两种方言共用，
不会出现「给 PG 维护了第二套转义、结果两边字符不一样」这种最难查的错。

## 3. 表结构（9 张）

```
partition      分区：付费方 / 供给结构 / 产值口径 / 建不建单元
occupation     职业：交付物 / 提供者 / 计费 / 承接通道（**不带归属**）
membership     归属边：职业 × 分区 × 轴 × 权重 —— 多视角是常态
gb_catalog     职业分类大典（2022）1636 条，只读旁证
scale_metric   六口径规模账：**一行一个口径**，缺的口径也占一行并写明为什么缺
money_node     资金流节点：五个机构部门 + 行业池（declared_* 是外部对账口径）
money_flow     资金流：from → to 双边记账，金额全用元（null = 待补，不是 0）
money_gap      对账差额与未观测登记：允许有差额，不允许差额没人解释
dataset_meta   数据集元信息：版本、生成器、口径免责
```

五条设计约束，不是风格问题：

1. **归属单独成表**。把 `partition_id` 塞回 `occupation` 就退化成硬分类：
   一个职业不能同时接两个行业的活，改分区还得批量改职业。
2. **产值口径必须同列**。`gdp_cny` 旁边就是 `gdp_kind`，两者不能分表——
   分开存的话，总有人 `sum(gdp_cny)` 时忘了 join 口径，把 GMV 和增加值加在一起。
3. **NULL ≠ 0**。无市场口径的分区 `gdp_cny` 是 `NULL`，不是 0；填 0 会把
   「没数据」伪装成「实测为零」，而这两种情况在决策上是反的。
4. **六口径摊成行，不摊成列**。`scale_metric` 一行一个（分区，口径）。
   摊成宽表的话，「六个口径全空」就变成六个 NULL，和「这个分区根本没登记」
   长得一样——隐身这件事在库里就看不见了。摊成行之后，缺的口径照样占一行，
   `missing_reason` 里就是那句「为什么这一格是空的」。
5. **行业池节点由 pools 段派生**。同一个分区在 `pools` 里已经声明过
   「它是钱的一个容器」，再手抄一个 node 就是同一件事存两份；而错的那份
   不会报错，只会让钱流向一个不存在的节点（`pool:<分区id>`）。

## 4. 六口径与资金流：两条「防漏」的账

两本账都是**框架先立、数后补**。用 `null` 留空、用 `missing`/`unobserved`
把「为什么这里是空的」写成可校验的句子——这比编一个数填上强得多，
因为编出来的数后面所有人都会当真。

### 4.1 `scale_metric`：行业不该因产值缺失整体隐身

```
partition    metric        value    unit  kind          missing_reason
manufacturing gdp       3.3e13   CNY   value_added   （有数）
manufacturing employment 8000    wan                 （有数）
manufacturing valuation   NULL    ——                 制造业板块市值按 GB/T 门类无法对齐
admin-office  profit       NULL   ——                 企业内部职能，无独立利润口径
```

只要六格里任一有数，这个行业就还在表里，能排序、能比较、能进分母。
六格全空必须逐格写原因，否则 `validate` 第 22 条报错。

### 4.2 `money_flow`：钱不会凭空生灭

```sql
-- 哪个节点的流入对不上外部口径？这就是「漏画了流向」的那一栏
SELECT n.id, n.name, n.declared_in_cny, SUM(f.amount_cny) AS traced
FROM money_node n JOIN money_flow f ON f.dst = n.id
WHERE n.declared_in_cny IS NOT NULL
GROUP BY n.id;

-- 有多少条边的数额还没补（图完整度）
SELECT COUNT(*) FILTER (WHERE amount_cny IS NULL) AS pending FROM money_flow;
```

「全局流入合计 = 全局流出合计」是双边记账的**恒等式**，查它只会永远为真。
真正要查的是上面那条：**节点与外部口径对账**。

## 5. 产值口径：加总只允许同口径

这是本轮补的最后一刀。之前 41 个分区都有 `gdp_cny`，但混着四种完全不同的钱：

| `gdp_kind` | 含义 | 能不能加总 |
|---|---|---|
| `value_added` | 增加值（GDP 口径） | ✅ 可相互加，可与统计年鉴对表 |
| `gross_output` | 总产值/总产出（含中间投入） | ⚠️ 会重复计算 |
| `revenue` | 营业收入/行业收入 | ⚠️ 含中间投入 |
| `market_size` | 市场规模（第三方测算） | ⚠️ 范围常与统计口径不同 |
| `cost_total` | 成本总额（物流费用/R&D 经费） | ❌ 本身是投入不是产出 |
| `gmv` | 交易额/流水 | ❌ 非增加值 |
| `none` | 无市场口径 | — 不参与任何加总 |

现实数据的分组结果（`industry partitions` 末尾会打出来）：

```
value_added     6 个分区有数  合计    55.0 万亿元  置信度 高4/中2/低0
gross_output    5 个分区有数  合计    41.6 万亿元  置信度 高1/中3/低1
cost_total      3 个分区有数  合计    29.5 万亿元  置信度 高1/中2/低0
revenue        12 个分区有数  合计    25.1 万亿元  置信度 高1/中9/低2
gmv             2 个分区有数  合计    17.0 万亿元  置信度 高1/中0/低1
market_size     7 个分区有数  合计    13.6 万亿元  置信度 高0/中5/低2
none            6 个分区（刻意留空，不参与加总）
```

**可对外引用的只有 55.0 万亿（增加值口径）**。旧版那句「合计 181.7 万亿」是把
电商 15 万亿 GMV、物流 18 万亿成本总额、建筑业 32 万亿总产值和制造业 33 万亿增加值
加在了一起——每个数都抄对了，加起来完全是另一回事。数字越大越误导，这类错最难被看出来。

`gdp_confidence` 同时落库：

- `high` 官方统计直接可取；
- `medium` 官方总额按分项拆分，或行业组织年度报告；
- `low` 第三方测算或量级拍脑袋 —— **低置信的数可以排序定权重，不许对外引用**。

## 6. 与岗位画像库（`data/db/hanghang.db`）的分工

仓库里有两套库，别混：

| | 行业分区库（本文） | 岗位画像库（M11.3） |
|---|---|---|
| 结构源 | `engine/industry_schema.py` | `rolecard/schema_sql.py` |
| 内容 | 职业 / 分区 / 归属边 / 大典 | 岗位卡 / 六维画像 / 工序 / 就绪度 |
| 库文件 | `out/industry-db/industry.sqlite` | `data/db/hanghang.db` |
| 何时合并 | 将来接客户库时按 `industry_unit.unit_id` ↔ `partition.unit_id` 关联 |

两套都是「结构单源 + 双方言 + 产物可校验」，规矩一致，只是回答的问题不同：
一个回答「这个行业谁付钱、多少钱」，另一个回答「这个岗位怎么干活、还差什么」。

## 7. CI 守什么

`.cnb.yml` 的 PR 检查与 main 全量回归各加一条：

```bash
python3 scripts/export_industry_db.py --check
```

它做两件事，第二件才是关键：

1. 提交的 DDL 与代码单源是否一致（改了字段忘了重生成 → 红）；
2. **真灌一份临时 SQLite 再读回行数**，逐表比对（只检查文件非空等于没验 ——
   占位符个数与列数不匹配、转义写错、外键顺序颠倒，文件都照样非空）。

回归用例 `tests/test_industry_import_m11.py`（13 项）另外钉住：口径标签必须存在且与
数字互斥一致、拼错的口径类型要报、分组汇总不丢行不重复计、csv/sqlite 出口都带
`gdp_kind`、数据 SQL 不含方言扩展。
