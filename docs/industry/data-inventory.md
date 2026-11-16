# 数据盘存清单

由 `scripts/gen_data_inventory.py` 生成，**请勿手改**。改动数据后重跑本脚本，`--check` 会在 CI 里拦住过期产物。

## 一句话：东西都在哪

| 落点 | 是什么 | 谁在用 |
|---|---|---|
| `data/*.yaml` | 权威源：人工维护、可评审、可回滚 | 引擎 + 知识库切片 |
| `data/db/**/*.sql` | 结构产物：DDL 进版本库（契约），数据不进 | 客户建库 / CI 往返自检 |
| `out/industry-db/*` | 导出产物：`industry export` 生成 | BI / 制品库 / 交接 |
| CNB 知识库 | `**/*.md` 自动切片（排除 `poc/**`） | 检索问答 |

## 一、权威源（改数据只改这些）

| 文件 | 条目 | 被谁读 | 大小 | 说明 |
|---|---|---|---|---|
| `data/industry-occupations.yaml` | 178 occupations | `IndustryDatabase` | 39 KB | 职业原子表：最小单目标，不带归属字段 |
| `data/industry-partitions.yaml` | 41 partitions | `IndustryDatabase` | 49 KB | 分区（职业聚类结果）：付费方/供给结构/产值口径/建不建单元 |
| `data/occupation-memberships.yaml` | 186 memberships | `OccupationAxis` | 24 KB | 归属边：职业 × 分区 × 轴 × 权重（权重不是概率） |
| `data/industry-scales.yaml` | 41 scales | `ScaleLedger` | 20 KB | 六口径规模账：盈利/资产/估值/资源消耗（gdp 与就业在 partition 上） |
| `data/industry-money-flows.yaml` | 27 flows | `MoneyFlowBook` | 16 KB | 资金流守恒账：部门 + 行业池 + 双边记账 + 对账口径 |
| `data/industry-official-baseline.yaml` | 17 benchmarks | `OfficialBaseline` | 19 KB | 官方口径基准：逐年表值 + 分区↔基准对表关系 |
| `data/industry-input-output.yaml` | 35 accounts | `InputOutputBook` | 28 KB | 投入产出账：生产法三端 + 中间投入构成 + 池切分锚点 |
| `data/industry-strategy.yaml` | 41 partitions | `StrategyView` | 51 KB | 行业战略视图：价值链/利润池/杠杆/驱动/风险/AI 承接面/岗位落点（粒度只到岗位/角色，工序与话术由 AI 上岗后补） |
| `data/industry-classes.yaml` | 不适用（契约/索引文件，非条目） | `ClassStore` | 4 KB | 行业类词表汇总入口（类目本体在 data/industry-classes/*.yaml），公司靠索引现查不落库 |
| `data/unit-index.yaml` | 14 units | `Registry` | 33 KB | 行业单元索引：路由的注册表 |
| `data/coverage-target.yaml` | 41 targets | `CoverageTracker` | 14 KB | 覆盖目标全集（分母）与各行业建议搜集渠道 |
| `data/rolecard-schema.yaml` | 不适用（契约/索引文件，非条目） | `rolecard` | 5 KB | 岗位卡字段契约（顶层是契约元信息，字段定义在 required/optional 段） |

## 二、结构产物（进版本库，是契约）

| 文件 | 行数 | 生成者 | 说明 |
|---|---|---|---|
| `data/db/industry/00-schema.sqlite.sql` | 231 | `scripts/export_industry_db.py` | SQLite DDL：买服务器直接建库用（SQLite 方言） |
| `data/db/industry/00-schema.postgresql.sql` | 231 | `scripts/export_industry_db.py` | PostgreSQL DDL：买服务器直接建库用（PG 方言） |
| `data/db/00-schema.sqlite.sql` | 215 | `scripts/build_role_db.py` | 岗位画像库 DDL：另一套库：岗位画像/工序/就绪度 |
| `data/db/00-schema.postgresql.sql` | 215 | `scripts/build_role_db.py` | 岗位画像库 DDL (PG)：同上，PG 方言 |
| `data/db/00-class-tables.sql` | 60 | `scripts/export_class_db.py` | 行业类库 DDL：行业类词表建库结构 |

## 三、导出产物（不进版本库，可秒级重建）

```bash
python3 src/hanghang/cli/main.py industry export --out out/industry-db
```

| 文件 | 说明 |
|---|---|
| `out/industry-db/industry-db.json` | 全量 JSON（含四本账），给 BI/知识库直接吃 |
| `out/industry-db/partitions.csv` | 分区扁平表 |
| `out/industry-db/occupations.csv` | 职业扁平表（含多视角边） |
| `out/industry-db/scales.csv` | 六口径一行一个口径，缺的也占一行 |
| `out/industry-db/money-nodes.csv` | 资金流节点（带 inflow/outflow/gap_ratio） |
| `out/industry-db/money-flows.csv` | 资金流明细（memo 列区分「摊开看」与真钱） |
| `out/industry-db/baseline-check.csv` | 官方基准对表结论（一分区一行，带偏差） |
| `out/industry-db/io-accounts.csv` | 生产法三端 + 增加值率 + 能否切分 |
| `out/industry-db/io-input-plan.csv` | 中间投入构成还缺什么、卡住哪一步、谁在消费这个分区 |
| `out/industry-db/strategy.csv` | 行业战略视图：价值链/利润池/AI 承接面/岗位落点 |
| `out/industry-db/data-inventory.csv` | 本清单自身 |
| `out/industry-db/industry.sqlite` | 单文件库（13 表） |
| `out/industry-db/00-schema.sqlite.sql` | 建库 DDL（SQLite） |
| `out/industry-db/00-schema.postgresql.sql` | 建库 DDL（PostgreSQL） |
| `out/industry-db/10-data.sql` | 与方言无关的数据 SQL（10-data.sql 是文件名，非表数） |

## 四、库里的行数（导出时实测）

| 表 | 行数 |
|---|---|
| `dataset_meta` | 6 |
| `partition` | 41 |
| `occupation` | 178 |
| `membership` | 186 |
| `gb_catalog` | 1636 |
| `scale_metric` | 246 |
| `money_node` | 13 |
| `money_flow` | 27 |
| `baseline_series` | 33 |
| `baseline_link` | 41 |
| `io_account` | 41 |
| `money_gap` | 11 |
| `strategy_view` | 41 |

合计 2500 行 / 13 张表（`export_industry_db.py --check` 会真灌一份临时库再读回来比对）。

## 五、五本账各守什么

| 账 | 文件 | 守的一件事 | 抓得住什么 |
|---|---|---|---|
| 六口径规模账 | `data/industry-scales.yaml` | 行业不因产值没统计就整体隐身 | 任一格有数就在表里；缺的格子必须写原因 |
| 资金流守恒账 | `data/industry-money-flows.yaml` | 钱不会凭空生灭 | 节点与外部口径对账偏差超 10% 即报；`memo` 边区分「摊开看」与真钱 |
| 官方口径基准 | `data/industry-official-baseline.yaml` | `high` 置信度必须可核对 | 同口径 + 同年份对表；口径不同（`incomparable`）不许相减 |
| 投入产出账 | `data/industry-input-output.yaml` | 切分不重复计 | 生产法恒等式三端闭合；GMV/成本总额不许当增加值锚点 |
| 行业战略视图 | `data/industry-strategy.yaml` | 钱为什么在这、AI 该站哪一段 | 粒度只到岗位/角色：工序与话术由 AI 上岗后补，写死在这里的那版一定过期 |

## 六、平台路径

- 仓库内：`data/`（源）、`data/db/industry/`（结构）、`out/industry-db/`（导出）
- 知识库：本文件与 `docs/industry/*.md` 会被切成片段供检索（`.cnb.yml` 的 `knowledge update`，include `**/*.md`、exclude `poc/**`）
- 库：`data/db/industry/00-schema.{sqlite,postgresql}.sql` + `out/industry-db/10-data.sql`，拿到不跑 Python 也能装
