# 行业分区库 · 结构产物

由 `scripts/export_industry_db.py` 生成，请勿手改。
数据 SQL 不在这里（可从 yaml 重建），由 `industry export --out out/industry-db` 生成 `10-data.sql`。

## 导入

```bash
# SQLite
sqlite3 hanghang.db < data/db/industry/00-schema.sqlite.sql
sqlite3 hanghang.db < out/industry-db/10-data.sql
# PostgreSQL
psql -d hanghang -f data/db/industry/00-schema.postgresql.sql
psql -d hanghang -f out/industry-db/10-data.sql
```

详见 `docs/industry/industry-db-import.md`。

## 表

- `dataset_meta`（2 列）— 数据集元信息：拿到库先知道它是哪版、按什么口径统计的
- `partition`（33 列）— 行业分区（职业聚类结果）：付费方 / 供给结构 / 产值口径 / 建不建单元
- `occupation`（11 列）— 职业（原子最小单位，不带归属）：交付物 / 提供者 / 计费 / 承接通道
- `membership`（5 列）— 归属边：职业 × 视角 × 轴 × 权重（权重不是概率，权重和不必为 1）
- `gb_catalog`（9 列）— 职业分类大典（2022）参考表：只读旁证，补缺口时不必再找原始 PDF
- `scale_metric`（9 列）— 六口径规模账：一行一个口径，缺的口径也占一行并写明为什么缺
- `money_node`（8 列）— 资金流守恒账节点：五个机构部门 + 行业池
- `money_flow`（7 列）— 资金流：from → to 双边记账，金额全用元（口径混用是这类账的头号死法）
- `baseline_series`（9 列）— 官方口径基准逐年表值：一个基准一个口径，一年一行
- `baseline_link`（12 列）— 分区↔官方基准对表关系：equal/envelope 要比数值，incomparable 只登记
- `io_account`（12 列）— 投入产出账：生产法三端 + 增加值率 + 行业池切分可行性
- `money_gap`（5 列）— 对账差额与未观测登记：允许有差额，不允许差额没人解释
- `strategy_view`（14 列）— 行业战略视图：价值链/利润池/杠杆/驱动/风险/AI 承接面/岗位落点

## 与另一套库的分工

`data/db/hanghang.db`（`scripts/build_role_db.py`）装的是岗位画像/工序/就绪度；
本目录装的是职业/分区/归属边/产值口径。两套都「结构单源 + 双方言 + 产物可校验」，
回答的问题不同：一个问「这行业谁付钱、多少钱」，一个问「这岗位怎么干活、还差什么」。
