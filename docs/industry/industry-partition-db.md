# 行业分区定义库（M11）· 职业是单目标，行业是聚类

> 解决的问题：过去行业靠"命名"堆叠，命名一变就漏、就重、就分不清谁是谁。
> 这里把**职业**定成解耦的最小单目标，**行业分区**只记录"这批职业为什么聚在一起"。

## 两层结构

```
occupation（职业，最小单位，稳定主键）
        │  occupation.unit_id / unit_role
        ▼
partition（行业分区 = 职业聚类结果：聚类依据 + 付费方 + 供给结构 + 产值口径）
        │  partition.unit_id
        ▼
unit（已注册的行业单元，真正能被路由到的执行体）
```

三层各管一件事：

- **职业层**：一个职业一条记录，`id` 是主键（如 `translator`）。行业改名不动它。
  职业通过**单值** `unit_id` 挂到唯一分区；多归属暂不支持（要扩成 `partition_ids`
  并同步 `members_of`/`validate`/导出，本轮不做）。没挂分区的职业照样登记
  → **缺口永远可见，不会静默丢失**。
- **分区层**：不写职业清单，只写清"为什么聚类"。成员由 `occupation.unit_id` 反查得到，
  **不存在第二份清单**，也就不会两份数据打架。
- **单元层**：只有建了单元的分区才能真正被路由。`status` 区分
  `covered`（已建）/ `pending`（待建）/ `evaluated`（评估后明确不建，不计入分母）。

## 数据文件

| 文件 | 内容 |
|------|------|
| `data/industry-occupations.yaml` | 职业表：`id/name/unit_id/unit_role/deliverable/provider/billing/baseline_occupation` |
| `data/industry-partitions.yaml` | 分区表：`cluster_basis/demand_side/provider_mix/gdp_cny/gdp_scope/gdp_source/status` |

## 关键字段口径

- `provider`（提供者）：`ai` / `hybrid` / `human` —— 该职业的供给主要来自谁。
- `billing`（谁付钱）：`subscription`订阅 / `hourly`计时 / `project`项目 /
  `commission`佣金 / `retainer`顾问 / `usage`按次 / `salary`雇员工资 / `free`公共 / `licensing`授权。
- `provider_mix`（分区供给结构）：**由成员职业的 `provider` 字段实测统计**
  （AI/混合/纯人各占多少条），汇总与分区行同源。分区手写的估算值降级为
  `provider_mix_estimated` 只作对账留档，偏差 > 25 个百分点 `validate()` 会报出来；
  没有成员职业的分区不给实测值（三个 0），**不把"无数据"伪装成"纯人供给"**。
- **实测口径里没有值就是 0，不是估算。** `provider_mix` 的契约是"成员职业实测"，
  所以无成员分区的 `provider_mix` 一律 `{ai:0, hybrid:0, human:0}`，
  原人工估算搬进 `provider_mix_estimated`（5 个 `evaluated` 分区就是这么改的）。
  `validate()` 会拦住"无成员却有非零实测值"这种手写值冒充实测的写法，
  csv / sqlite 的 `provider_ai`（实测列）与 `provider_ai_declared`（留档列）也各归其位。
- `gdp_cny`（年产值）：**量级参考，不是官方统计**，用于分区排序定权重。
  无市场口径的分区（行政办公、政务公共、国际事务）**刻意留 `null`**，绝不填 0 冒充数据。
- `baseline_occupation`：是否进覆盖分母。目标基线刻意收敛，避免把上千个细类职业
  塞进来把覆盖率稀释成没有意义的数字。

## 命令

```bash
# 分区定义表（按产值降序）
python3 src/hanghang/cli/main.py industry partitions --top 10

# 单分区详情：聚类依据/付费方/供给结构/成员职业
python3 src/hanghang/cli/main.py industry partition video-media

# 职业表（可按分区/提供者/收费方式过滤）
python3 src/hanghang/cli/main.py industry occupations --provider ai
python3 src/hanghang/cli/main.py industry occupations --unassigned   # 未挂分区的职业=缺口

# 数据一致性自检（职业 ↔ 单元岗位 双向对齐）
python3 src/hanghang/cli/main.py industry check

# 导出扁平表（json/csv/sqlite），供 CNB 制品库 / 知识库消费
python3 src/hanghang/cli/main.py industry export --out out/industry-db
```

Web：`GET /api/industry-db`（只读，含 `problems` 自检结果）。

## 关于"数据库"与存储

刻意**不引入外部数据库服务**：

- yaml 是唯一事实源，diff 可评审、可回滚、可被知识库直接切片；
- 需要查表/联表时 `industry export` 生成 `industry.sqlite` 单文件库，
  可随制品库发布，拿到即用，零部署；
- `partitions.csv` / `occupations.csv` 是扁平表，任何 BI / 表格工具都能直接吃。

CNB 平台自带的存储（制品库 + 知识库）作为发布通道，仓库里的 yaml 才是权威源。

## 新增一个分区或职业

```yaml
# 1) 先登记职业（哪怕还没有单元）
- {id: podcast-editor, name: 播客剪辑师, deliverable: 物料, provider: hybrid,
   billing: project, baseline_occupation: false, note: "音频内容，待归分区"}

# 2) 再登记分区聚类（成员自动反查，无需手写）
- id: audio-content
  name: 音频内容
  aliases: [播客, 有声书]
  cluster_basis: [交付物同源(音频), 付费方同行(平台分账)]
  demand_side: [平台分账, 品牌冠名]
  provider_mix_estimated: {ai: 55, hybrid: 40, human: 5}  # 单元未建时的人工估算
  gdp_cny: null            # 没有可靠口径就留空，不要编
  gdp_scope: 无独立统计口径
  gdp_source: 不适用，刻意留空
  status: pending
```

然后把职业的 `unit_id: audio-content` 填上，`industry check` 会立刻告诉你还缺什么。

## 与覆盖进度的关系

`coverage`（M2 覆盖进度）的岗位基线现在**优先取职业库**：
职业库有登记就用基线职业数，没有才回落到 `coverage-target.yaml` 手写的 `target_roles`。
即"职业库是权威，coverage-target 只是兜底"，避免两处手写岗位各自漂移。

每行带 `roles.baseline_source`，兜底可见、不静默：

| 值 | 含义 |
|---|---|
| `occupation` | 取职业库基线（权威源） |
| `unit_roles` | 分区无职业登记 → 回落注册岗位数 |
| `target_roles` | 分区无职业登记 → 回落 coverage-target 手写岗位 |
| `stale` | 分区有职业登记但**全部非基线** → 权威源失效，`compute()["problems"]` 会报 |

职业库是权威源，但权威源坏掉不能让 `/api/coverage` 和 `coverage` 命令一起倒：
`_occupation_baseline` / `_baseline_source` 走受保护的 `_check_partition` / `_members`，
读取异常、返回 `None`、返回非列表一律按兜底口径返回**并写入 `problems`**
（同一分区只记一条，避免两个读取点刷屏两遍）。

`CoverageTracker(industry_db=...)` 是三态的，别再靠 `None`/`False` 猜：

| 传入 | 行为 |
|---|---|
| `None`（默认） | 自动构造职业库 |
| `DISABLED_DB`（`hanghang.engine.coverage` 导出） | 显式禁用，岗位基线一律走兜底 |
| 其它对象 | 注入实例（测试替身/外部库），不自动构造；读取失败走降级 |

## validate() 的 8 条校验

| # | 校验点 | 说明 |
|---|---|---|
| 1 | 职业 `unit_id` 存在性 | 既非已注册单元也非已知分区 → 报错 |
| 2 | 分区 `covered` 必须有 `unit_id` | 否则纸面覆盖 |
| 3 | 分区 `unit_id` 必须已注册 | 指向不存在的单元 → 报错 |
| 4 | 分区 `unit_id` 与成员挂靠分区一致 | 成员 `unit_id` 应等于分区 id |
| 5 | 已建单元成员必须有 `unit_role` | 建了单元还没岗位名 → 路由永远命中不了 |
| 6 | 未建单元成员填了 `unit_role` 必须在 `planned_roles` 里 | 堵住随手编角色名 |
| 7 | `evaluated` 分区不得有 `unit_id` | 状态互斥，"不建单元"却又挂单元 |
| 8 | `provider_mix` 对账 | 有成员看漂移 > 25pt；无成员必须 0/0/0 |

第 5 条的现实意义：18 个待建分区、89 个成员的 `unit_role` 目前全为空，
靠"分区没 `unit_id` 所以不校 unit_role"绕过去。一旦这些分区建单元，
这条会立刻把缺口打出来——不是等到上线才发现路由命中不了。
