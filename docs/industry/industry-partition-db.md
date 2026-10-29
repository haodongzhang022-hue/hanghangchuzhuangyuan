# 行业分区定义库（M11）· 岗位原子化，分类是筛选器

> 解决的问题：过去行业靠"命名"堆叠，命名一变就漏、就重、就分不清谁是谁。
> 这里把**岗位**定成原子的最小单位，**分类**只是"一种看法"，不是户籍。

## 三层结构（归属不再写在岗位身上）

```
occupation   原子岗位：唯一编号 OCC-000001 + slug，**没有归属字段**
      │
      ├── membership  边：岗位 × 视角 × 轴 × 权重（occupation-memberships.yaml）
      │
      ├── partition   视角/聚类：聚类依据 + 付费方 + 供给结构 + 产值口径
      │
      └── unit        执行体：真正能被路由到的行业单元（分区.unit_id）
```

三层各管一件事：

- **岗位层**：一个岗位一条记录，`code`（OCC-######）是唯一编号，`id` 是稳定 slug。
  **它不写"我属于哪个分区"**——改名、拆分、合并、重新聚类都不动这条记录。
- **边层**：岗位和视角之间的关系全部落在这里，带 `axis`（职业/行业/税收/产出）
  和 `weight`。同一岗位可以被任意多个视角同时引用；权重**不必相加为 1**：
  `0.6 + 0.5` 不是错误，是"两件活都真干"。想只看主要归属就按 `--min-weight 0.5` 筛。
- **分区层**：不写成员清单。成员是"按这个视角筛出来的结果"，不是"归属于它的东西"。
- **单元层**：只有建了单元的分区才能真正被路由。`status` 区分
  `covered`（已建）/ `pending`（待建）/ `evaluated`（评估后明确不建，不计入分母）。

### 为什么不再用单值 `unit_id`

单值归属是**硬分类**，它有三个躲不掉的毛病：

1. **丢信息**：写着"字幕翻译属于翻译本地化"，就再也表达不了"同一个人也接视频影视的活"。
2. **被管理绑架**：分区成了岗位的容器，改分区就得批量改岗位，改错了没人发现。
3. **假装确定**：现实里大多数岗位本来就跨多个行业（会计跨所有行业、客服跨所有行业），
   强制单选一个"正确归属"必然错，而且错了看不出来。

所以：**岗位原子化，归属模糊化，分类当筛选器用。**

## 数据文件

| 文件 | 内容 |
|------|------|
| `data/industry-occupations.yaml` | 岗位表：`code/id/name/deliverable/provider/billing/access/baseline_occupation`（**无归属字段**） |
| `data/occupation-memberships.yaml` | 边的表：`occupation/partition/axis/weight/unit_role` |
| `data/industry-partitions.yaml` | 分区表：`cluster_basis/demand_side/provider_mix/gdp_cny/employment/axes/status` |

老数据的 `occupation.unit_id` 仍被识别（推成一条 `weight=1` 的边），但它的含义是
"这份数据以前只有这一个说法"，**不是"只能属于这里"**。

## 用法：从"归属"改成"筛选"

```bash
# 一个岗位被哪些视角看见（多归属的正面表达）
python3 src/hanghang/cli/main.py industry occupation OCC-000021
python3 src/hanghang/cli/main.py industry occupation data-analyst

# 按任意维度组合筛，不需要先决定"归到哪"
python3 src/hanghang/cli/main.py industry filter --partition e-commerce
python3 src/hanghang/cli/main.py industry filter --provider ai --min-weight 0.5
python3 src/hanghang/cli/main.py industry filter --axis tax --access non_market

# 视角内的成员按权重降序，权重 < 1 标出来（那是"顺带干"，不是不合格）
python3 src/hanghang/cli/main.py industry partition e-commerce
```

## 自检守的是什么

`industry check` 在软归属模型下改守这几条（不守"归属唯一"这种伪命题）：

1. 唯一编号必须唯一、格式 `OCC-######`、与登记序号一致（编号漂移 = 跨表对齐全错）。
2. 边必须指向真实存在的分区（悬空边 = 这个角度静默什么都查不到）。
3. 边上的轴必须是已知轴（写错 = 这条边在任何视角下都不可见）。
4. `weight` 必须落在 `(0, 1]`（写 0 只是噪音，不想归属就别写这条边）。
5. 同一 `(岗位, 分区, 轴)` 不得重复（同一件事说了两遍）。
6. 建了单元的分区，其边上的 `unit_role` 必填且必须是该单元的岗位名。

**不校验**的：权重和是否为 1、一个岗位能挂几个视角、哪个视角是"正确归属"。
这些都是模糊的，硬管就是把人骗了。

## 四个问题，四把尺子（别压成一个判断）

上一版把"能不能直接向终端用户收费"当成唯一过滤器，结果同时丢掉两类人：
**口径没扫到的**（主播/陪玩，挂在别的行业下）和**付费方不是终端用户的**
（军人/消防/矿工，财政或项目款付费）。两种错混在一起，改起来互相打脸。

现在拆开：

```
职业（什么活）     → 一律登记，不设门槛
access（谁付钱）   → paid_direct / non_market / org_internal / household
axes（哪根轴成立） → 同一分区可被多根轴引用，不复制数据
status（建不建单元）→ covered / pending / evaluated
```

**`evaluated` 不等于忽略**：职业照样登记、画像照样统计、产值照样计入产出轴，
只是不建数字员工单元。"该不该被分析"和"要不要建执行体"是两件事。

## 关键字段口径

- `provider`（提供者）：`ai` / `hybrid` / `human` —— 该职业的供给主要来自谁。
- `access`（承接通道）：**回答"怎么和付费方接上"，不回答"值不值得分析"**。
  `paid_direct`（缺省，不写即此值）/ `non_market`（财政供养）/ `org_internal`（雇主预算）
  / `household`（家庭无酬）。`non_market` 说的是"不经过现金市场"，不是"没有价值"——
  财政本身就是购买力，只是采购通道不同。
- `axes`（视角）：`occupation`/`industry`/`tax`/`output`，缺省四轴都可见。
  **多视角 ≠ 多分区**：一份数据被多根轴引用，不是给每个视角复制一份。
- `employment`（从业人员，万人）：产出轴的另一半。有人没产值（军队/家庭无酬）
  也要有数；没口径请留空，**别填 0 冒充实测**。
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
  csv / sqlite 的 `provider_ai`（实测列）、`provider_ai_declared`（声明留档）、
  `provider_ai_estimated`（人工估算）三列各归其位。
  估算列必须导出：无成员分区的实测列恒为 0，唯一带人味的数就在估算列，
  不给出口下游只拿到一堆 0。
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
# 1) 先登记岗位（哪怕还没有任何视角引用它）——注意没有归属字段
- {code: OCC-000178, id: podcast-editor, name: 播客剪辑师, deliverable: 物料,
   provider: hybrid, billing: project, baseline_occupation: false,
   note: "音频内容，还没被任何聚类看上"}

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

最后在 `data/occupation-memberships.yaml` 里加一条边，把这个岗位**看见**：

```yaml
- {occupation: podcast-editor, partition: audio-content, axis: occupation, weight: 0.8}
```

注意这不会改变岗位本身。同一个岗位以后要是也接视频的活，再加一条
`{partition: video-media, weight: 0.5}` 就行——两条并存，不是二选一。

### 什么该合成一个分区，什么必须拆开

判据只有一条：**付费方与交付方式是否同一件事**。

- 同一个付费方、同一个交付形态 → 可以合并（软件研发里架构师和开发都卖项目工期）。
- 付费方不同 / 交付形态不同 → 必须拆开，否则合并后谁也说不清这行赚谁的钱。
  已按这条拆过的三处：

| 原分区 | 拆成 | 差别 |
|---|---|---|
| 翻译本地化 | 口译服务 / 翻译本地化 | 现场同步按时计费 vs 异步文本按量计费，AI 承接面差一个量级 |
| 电竞直播陪玩 | 直播与网络表演 / 电竞竞技 | 打赏+坑位 vs 奖金+工资+票务+陪玩抽成 |
| 体育健身 | 体育健身 / 赛事与场馆运营 | 面个人的课时制 vs 面机构的项目制 |

配套规矩：

1. **拆分不给新产值/就业口径**。合并口径没拆开之前，新分区一律 `null` 并写明原因，
   不按比例切一份 —— 切一份等于同一批钱、同一批人数算两遍。
2. **旧 id 不许复活**。`test_folded_partitions_are_gone` 会拦住"下一轮又被合回去"。
3. **层级不能混**。职业 id 与分区 id 不得撞名，分区名不得正好是某个岗位名；
   把岗位当行业写进分区表，会让"这个行业谁付钱"永远答不上来。

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

## validate() 的 19 条校验（软归属版）

编号与 `industry_db.py` 里 `validate()` 的注释逐条对应。**条数的唯一来源是代码里的
`IndustryDatabase.VALIDATE_CHECK_COUNT`**，README、本文标题、CLI 回执都读它；
表格行数由 `tests/test_occupation_axis.py::test_validate_check_count_is_single_source`
断言与常量一致，抄漏一条会红。（此前这里指向的 `tests/test_industry_filter_partition.py`
**不存在**——守卫写在文档里、代码里没有，等于没有守卫。）

| # | 校验点 | 说明 |
|---|---|---|---|
| 1 | 主键唯一且非空 | 空 id 让分子分母一起虚增；重复 id 让成员被静默丢弃、覆盖率一起失明 |
| 2 | `status` 必须是 `covered`/`pending`/`evaluated` | 拼错或漏填的分区既不进分母也不报错，覆盖率会静默变好看 |
| 3 | 老单值 `unit_id` 存在性 | 既非已注册单元也非已知分区 → 报错（仅对没有 `profile` 的老数据） |
| 4 | 分区 `covered` 必须有 `unit_id` | 否则纸面覆盖 |
| 5 | 分区 `unit_id` 必须已注册 | 指向不存在的单元 → 报错 |
| 6 | 分区 `covered` 必须有成员职业 | 有单元却筛不出岗位 = 纸面覆盖，数值不失真但缺口必须可见 |
| 7 | `evaluated` 分区不得有 `unit_id` | 状态互斥，"不建单元"却又挂单元 |
| 8 | 软归属的边自检 | 悬空视角 / 未知轴 / 权重越界 / 同边重复 / 唯一编号缺失或重号，逐条报出 |
| 9 | 已建单元的边必须有 `unit_role` | 建了单元还没岗位名 → 路由永远命中不了 |
| 10 | 未建单元的边填了 `unit_role` 必须在 `planned_roles` 里 | 堵住随手编角色名 |
| 11 | `provider_mix` 对账 | 有成员看漂移 > 25pt；无成员必须 0/0/0 |
| 12 | 注册单元的每个 role 都有职业认领 | 新增岗位不能漏登记 |
| 13 | 数据文件必须读到 | 空库不能"自检通过"（0 分区 0 职业全绿才是最难发现的故障） |
| 14 | 大典映射自洽 | `gb_code` 必须真实存在；映射的 `occur_id` 必须真实存在（职业改名后映射会悬空） |
| 15 | `access` 枚举合法 | 写错（如 `non-market` 带连字符）会静默回落 `paid_direct`，把"财政供养"念成"现金市场" |
| 16 | `axes` 是合法非空轴 | 空视角 = 任何看板都查不到它，而覆盖率不会变红半格 |
| 17 | `employment` 非负数或留空 | 填 0 会把"没口径"伪装成实测；0 和 null 语义不同 |
| 18 | `pending_partition` 必须指向真实分区 | 只在 `note` 里写"待补"是隐形契约，机器看不见；已兑现却不清字段也报 |
| 19 | `planned_roles` 骨架双向反查 | 骨架里有、本分区没有任何边认领 → 骨架悬空（说了要建、没人负责，建成即对不上）。只认本分区的边：拿别处的同名边背书等于允许凭空加名字 |

**明确不校验**：权重和是否为 1、一个岗位能挂几个视角、哪个视角是它的"正确归属"。
这些在现实里本来就是模糊的，硬管只会让数据说谎。

第 1、2、6 条是"数据看起来没问题、其实分母被悄悄缩小"的三条暗沟：分区 id 写重了、
`status` 拼成 `coverd`、标了 `covered` 却没登记职业——三种错都不会让覆盖率变红，
只会让它变好看。第 8 条尤其容易漏：`members_of()` 按分区 id 反查，
挂错单元的职业在所有分区的成员列表里都查不到，必须在成员循环之外单独扫一遍全量职业。

第 9 条的现实意义：待建分区的成员 `unit_role` 目前为空（岗位名那时本来就不存在），
靠"未建单元不校 `unit_role`"绕过去。一旦这些分区建单元，这条会立刻把缺口打出来
——不是等到上线才发现路由命中不了。

第 10 条曾经是"写着在跑、其实没跑"：旧实现是 `if role and planned and role not in planned`，
`planned_roles` 为空就整条短路跳过。测试能过是因为测试自己先造了 `planned_roles`——
守的是逻辑，不是"这条校验真的在跑"。现在补了配套报错：**有成员、有人填了 `unit_role`，
但分区压根没声明骨架**，直接报出来，不会因为判据缺失而静默放行。

第 18 条针对的是另一类隐形契约：8 个职业的归属只写在 `note` 里（"待补""可挂 xxx"），
人看得懂，机器看不见。`pending_partition` 把这份意向变成数据——写错分区会报，
意向兑现了却不清字段也会报。

第 19 条补的是第 10 条的另一半：第 10 条只保证"成员填的岗位名在骨架里"，
**骨架本身是自由变量**——从 `planned_roles` 删一项、或凭空加一项，旧实现都返回 `[]`。
现在双向都查。三个边界写清楚：

- 已建单元的分区交给第 9 条（成员缺 `unit_role` 必报），不在这里重复报；
- `evaluated` 是评估后明确不建，骨架在那儿是留档，没人认领属预期；
- `unit_role` 为空仍是合法等待态（待建分区还没定岗位名），不报。

上线后立刻暴露一条真实现状：**20 个待建分区、81 个骨架岗位没有任何原子岗位对应**
（如 `finance-invest` 的 5 个顾问岗、`tourism-hospitality` 的 6 个岗）。这不是代码缺陷，
是"待建分区补职业"这项活本身没干完——逐项报会刷屏，所以按分区汇总一条，
只报还没认领的岗位名清单。测试 `test_real_data_still_self_consistent` 因此收窄为
"除骨架缺口外必须干净"，`test_skeleton_gap_is_counted_not_silently_dropped` 钉住缺口数量可见。

第 15、16 条是这一轮新增的两个暗沟，共同点是**错了不会变红，只会让数字失真**：
`access` 写错 → 通道结构里凭空多出一堆"现金市场"；`axes` 写空 → 这个分区
从所有视角看板里消失，但覆盖率一格都没掉。
