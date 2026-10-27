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

- **职业层**：一个职业一条记录，`id` 是主键（如 `translator`）。行业改名不动它，
  一个职业也能被多个分区复用。没挂分区的职业照样登记 → **缺口永远可见，不会静默丢失**。
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
- `provider_mix`（分区供给结构）：按**成员职业数加权**汇总，不让大产值行业淹没小行业。
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
  provider_mix: {ai: 55, hybrid: 40, human: 5}
  gdp_cny: null            # 没有可靠口径就留空，不要编
  gdp_scope: 无独立统计口径
  gdp_source: 不适用，刻意留空
  status: pending
```

然后把职业的 `unit_id: audio-content` 填上，`industry check` 会立刻告诉你还缺什么。

## 与覆盖进度的关系

`coverage`（M2 覆盖进度）的岗位基线现在**优先取职业库**：
职业库有登记就用职业数，没有才回落到 `coverage-target.yaml` 手写的 `target_roles`。
即"职业库是权威，coverage-target 只是兜底"，避免两处手写岗位各自漂移。
