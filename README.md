# 行行出状元 · 通用能力层

跨行业/跨岗位的路由编排总层。把各「行业单元」（如 dongjiagoushi 架构团队）当原子收编，在其上叠一层「自动识别行业/岗位 → 路由 → 交接 → 交叉 → 复合装配」的总编排层。

## 架构分层

```
L2 人类端点    = 仅入口(意图确认) + 出口(复核)
L1 通用能力层  = 本仓库：识别路由(M1) / 注册表(M2) / 前缀档案(M3)
               / 会话编排(M4含SLIB) / 交接总线(M5) / 复合装配(M6)
               / 指标观测(M7) / 能力索引(M8) / 状态管理(M9) / 上下文装配(M10)
               / 岗位画像(M11：六维评估+就绪度+工作流playbook)
L0 行业单元层  = 各行业单元(如 dongjiagoushi)，原子化收编
```

## 数据与库

画像与词表的**事实来源**是 `data/` 下的 YAML（人工维护、评审看得见）；
可查询的**结构**是用它建出来的真库：

```bash
python3 scripts/build_role_db.py            # 建 data/db/hanghang.db（17 张表 / 3500 行）
python3 src/hanghang/cli/main.py role db    # 看库里有什么
python3 src/hanghang/cli/main.py role db --sql "SELECT ..."
```

`data/db/00-schema.sqlite.sql` 与 `00-schema.postgresql.sql` 由同一份表定义渲染
（改表只改一处）；库不进版本库，由 `--check` 在 CI 里保证不落后于数据。
设计见 `docs/architecture/M11.3-实库-岗位与行业类落库.md`。

## 数据驱动设计（核心亮点）

**新增行业单元只需更新注册数据，无需修改代码。**

各单元在其注册文件中声明 `keywords`（岗位触发词），路由引擎从数据动态读取识别信号。当前已注册（14个行业单元）：

| 单元 | 行业 | 岗位 |
|------|------|------|
| dongjiagoushi | 软件研发 | secretary / architect / developer / reviewer / product |
| game-dev-unit | 游戏研发 | game_planner / level_designer / game_dev |
| legal-services | 法律咨询 | legal_counsel / contract_advisor / compliance_advisor |
| content-creation | 内容创作 | copywriter / media_operator / content_editor |
| data-analytics | 数据分析 | data_analyst / data_scientist / bi_engineer |
| e-commerce | 电子商务 | store_manager / ecom_marketer / customer_service |
| finance-accounting | 财务会计 | accountant / tax_advisor / finance_analyst / payroll_processor |
| marketing | 市场营销 | market_researcher / brand_planner / campaign_planner / pr_manager |
| education-training | 教育培训 | curriculum_designer / teacher / learning_advisor |
| healthcare | 健康医疗 | health_consultant / psychologist / medical_advisor / fitness_coach |
| home-design | 家装设计 | interior_designer / soft_furnish / project_manager |
| hr-services | 人力资源 | recruiter / comp_benefits / employee_relations / hr_advisor |
| admin-office | 行政办公 | admin_specialist / receptionist / document_archivist / meeting_coordinator |
| design-visual | 视觉设计 | graphic_designer / ui_designer / illustrator / brand_designer |

> 非重点/非大型行业默认集中本仓（`repo_ref` 留空待回填），较大行业才拆独立仓。

新增单元时只需在 `data/unit-index.yaml` 或 `data/industry-register.yaml` 中追加声明。

## 岗位画像（M11）：从"行业有"到"岗位上手"

行业单元回答「这行有没有」，**岗位画像回答「这个岗位能不能真上手干活、缺什么」**。

每个岗位一张卡，六维评估（分析 / 画像 / 插件 / 工作流 / 利益链条 / 核心能力），
由 `data/role-profiles/`（人写基线）× 注册表 × `data/workflow-templates/` 渲染成
`data/rolecards/`（可 diff 的产物），并给出 **0-100 就绪度 + A/B/C/D + 缺口清单**。

```bash
# 岗位就绪度表（哪个岗位能真上手、还缺什么）
python3 src/hanghang/cli/main.py role list
# 看一张岗位卡全貌（六维评估 + 就绪度 + 因子 + 缺口）
python3 src/hanghang/cli/main.py role show architect --unit dongjiagoushi
# 取岗位工作流的分步 playbook（Agent 照着干 / 导出 n8n / 导出代码桩）
python3 src/hanghang/cli/main.py role playbook contract_advisor --format text
python3 src/hanghang/cli/main.py role playbook accountant --format n8n
# 渲染可注入提示词的岗位卡文本块（也可由 context assemble 自动注入层A）
python3 src/hanghang/cli/main.py role context data_analyst
# 画像覆盖总览
python3 src/hanghang/cli/main.py role coverage --gaps
# 利益链条：只看行业类（公司靠索引现查、不落库）+ 校验 + 类目反查
python3 src/hanghang/cli/main.py role chain architect --unit dongjiagoushi
python3 src/hanghang/cli/main.py role chain --check
python3 src/hanghang/cli/main.py role chain --class 用户
```

已落地：14 个行业单元 / 50 个岗位全部有画像基线，就绪度均值 95.0，评级全 A。
行业当前用不上也没关系 —— **先立卡、如实给缺口，成熟时补数据即可**，新增岗位不改一行代码。

**利益链条只存类，不存公司**（M11.1）：链上写「钢材加工」「品牌方」「用人部门」这类行业类目，
具体公司靠类目上的 `index`（企业名录 / CRM / ATS / 内部主数据）运行时检索，
名录不进仓库。写成 `XX有限公司` 会被 `role chain --check` 在 CI 拦下——
换一个客户，整张卡不用重写。

设计与口径见 `docs/architecture/M11-岗位画像层.md`、`data/rolecard-schema.yaml`、
`data/industry-classes.yaml`。

## 快速开始

### 安装依赖
```bash
pip install -r requirements.txt
```

### 命令行用法

```bash
# 路由识别：对一句话意图做路由判定
python3 src/hanghang/cli/main.py route "既要架构设计又要落地开发"
# => 复合装配: dongjiagoushi 同session并装岗位 ['architect', 'developer']

python3 src/hanghang/cli/main.py route "帮我点个外卖"
# => 置信度不足，回落 L2 人工确认

# SLIB 会话级行业绑定（会话感知路由，同一会话只能绑定一个行业）
python3 src/hanghang/cli/main.py route "帮我做架构方案" --session "my-sess"
# => 首次路由自动绑定: my-sess → 软件研发(dongjiagoushi)

python3 src/hanghang/cli/main.py route "帮我写段代码" --session "my-sess"
# => 同行业消息：仍在软件研发内路由

python3 src/hanghang/cli/main.py route "帮我制定健身计划" --session "my-sess"
# => ⚠️ SLIB 跨行业冲突：会话已绑定「软件研发」，需开新会话处理健康医疗

# SLIB 手动绑定 / 查看 / 解绑
python3 src/hanghang/cli/main.py bind --session "sess-x" --unit "healthcare"
python3 src/hanghang/cli/main.py binding --session "sess-x"
python3 src/hanghang/cli/main.py bindings           # 列出全部绑定
python3 src/hanghang/cli/main.py unbind --session "sess-x"

# M11 行业分区定义库：职业是最小单位，行业是聚类结果
python3 src/hanghang/cli/main.py industry partitions --top 10   # 分区定义表(按产值降序)
python3 src/hanghang/cli/main.py industry partition video-media  # 单分区详情(聚类依据/付费方/成员职业)
python3 src/hanghang/cli/main.py industry occupations --provider ai  # 按提供者/收费方式过滤职业
python3 src/hanghang/cli/main.py industry occupations --unassigned    # 未挂分区的职业(=覆盖缺口)
python3 src/hanghang/cli/main.py industry catalog --search 护士   # 查职业分类大典(1636 个职业+国标编码)
python3 src/hanghang/cli/main.py industry catalog --gaps        # 大典里还没被挂上的细类(候选池)
python3 src/hanghang/cli/main.py industry check                  # 职业↔单元岗位 双向对齐自检
python3 src/hanghang/cli/main.py industry export --out out/industry-db  # 导出 json/csv/sqlite 扁平表
python3 src/hanghang/cli/main.py reference isco --search nurse   # 查 ISCO-08 国际职业分类(436 细类+1931 条官方示例职位名)
python3 src/hanghang/cli/main.py reference isco --code 2512     # 按编码看国际归属链路
python3 src/hanghang/cli/main.py reference sources               # 四根轴全景：职业/行业/税收/产出 各有哪些标准

# 列出已注册单元
python3 src/hanghang/cli/main.py units

# 按视角看同一批分区：职业 / 行业 / 税收 / 产出（多视角 ≠ 多分区）
python3 src/hanghang/cli/main.py industry axis output      # 产值 + 就业人数
python3 src/hanghang/cli/main.py industry axis             # 四根轴全景

# 需求侧承接通道：现金市场 / 财政供养 / 企业内部 / 家庭无酬
# （不直接付费 ≠ 不值得分析：军人/消防/矿工/家务都在这里，画像照样统计）
python3 src/hanghang/cli/main.py industry access
python3 src/hanghang/cli/main.py industry access --side non_market

# 查看「目标全集 vs 当前覆盖」行业/岗位覆盖进度表（覆盖率/待补缺口）
python3 src/hanghang/cli/main.py coverage
python3 src/hanghang/cli/main.py coverage --gaps   # 仅列出待通过渠道搜集补齐的行业缺口

# 按关键词多维搜索行业能力索引（M8，可加 --mode 指定 industry/capability/role 维度）
python3 src/hanghang/cli/main.py search "合同"
python3 src/hanghang/cli/main.py search "数据" --mode role

# 导出全量跨行业能力索引（含 能力标签→承接岗位 映射，供可视化聚合）
python3 src/hanghang/cli/main.py index

# 检测跨行业诉求并自动编排交接（M5）
python3 src/hanghang/cli/main.py cross-unit "需要软件架构设计并做游戏关卡策划"

# 查看运行指标
python3 src/hanghang/cli/main.py metrics

# 创建跨单元交接卡
python3 src/hanghang/cli/main.py handoff --source dongjiagoushi --target game-dev-unit --intent "需要游戏单元提供策划支持"

# M9 状态管理（StateCard/折叠/层级提交/秘书长多级树）
python3 src/hanghang/cli/main.py state init --session demo --objective "实现状态管理"
python3 src/hanghang/cli/main.py state add --session demo --title "设计数据模型" --files "models.py"
python3 src/hanghang/cli/main.py state add --session demo --title "实现折叠引擎" --files "fold_engine.py"
python3 src/hanghang/cli/main.py state add --session demo --title "交付完整模块" --type deliverable
python3 src/hanghang/cli/main.py state update --session demo --task demo-0001 --state done
python3 src/hanghang/cli/main.py state fold --session demo
python3 src/hanghang/cli/main.py state show --session demo
python3 src/hanghang/cli/main.py state compact --session demo
python3 src/hanghang/cli/main.py state submit --session demo --upstream parent

# M9 秘书长多级树（多级拓扑管理）
python3 src/hanghang/cli/main.py tree init --name project --display "秘书长" --objective "全局管理"
python3 src/hanghang/cli/main.py tree register --name project --session sub-a --display "秘书A" --parent project
python3 src/hanghang/cli/main.py tree register --name project --session leaf-1 --role developer --parent sub-a
python3 src/hanghang/cli/main.py tree show --name project          # 渲染树导航视图
python3 src/hanghang/cli/main.py tree rollup --name project        # 逐级向上汇总
python3 src/hanghang/cli/main.py tree submit-chain --name project --session leaf-1

# M9 原文归档（ContentArchive：折叠后原文不丢、编号可找回）
python3 src/hanghang/cli/main.py state archive --session demo --ref demo-seg001 --content "折叠前完整原文"
python3 src/hanghang/cli/main.py state retrieve --session demo --ref demo-seg001   # 取回原文全文
python3 src/hanghang/cli/main.py state refs --session demo                         # 列出已归档引用
python3 src/hanghang/cli/main.py state full --session demo                         # 可恢复完整视图

# M9 秘书并发归属与冲突仲裁（多 Agent 协作写同一状态）
python3 src/hanghang/cli/main.py state claim   --session demo --role 秘书A   # 声明归属/占用
python3 src/hanghang/cli/main.py state status  --session demo --role 秘书A   # 查看 owner/version
python3 src/hanghang/cli/main.py state release --session demo --role 秘书A   # 释放归属
python3 src/hanghang/cli/main.py arb list                                    # 列出冲突票据
python3 src/hanghang/cli/main.py arb show --ticket ARB-xxx                   # 查看票据详情
python3 src/hanghang/cli/main.py arb diff  --ticket ARB-xxx                  # 查看 A/B 字段级差异
python3 src/hanghang/cli/main.py arb review --ticket ARB-xxx --decision keep_a --resolver human-1 --reason "说明理由"
# 说明：多秘书并发写同一 StateCard 时，基于乐观版本号(base_version)仲裁；
#       基于旧版本写会抛 StateConflict 而非静默覆盖，归属越权写会抛 OwnershipDenied。
#       检测到冲突时走 M9+ 版本化仲裁：保存双方版本 → 字段级差异分析，
#       非重叠自动合并、重叠则生成 ReviewTicket 待 arb review 审核。

# M10 上下文装配（context: 三层隔离装配 / 规则表 / 缓存隔离校验）
# 说明：M10 防提示词冗余——静态层(缓存键) / 会话态层 / 按规则注入层，三层物理隔离。
python3 src/hanghang/cli/main.py context assemble --session ctx-1 --unit dongjiagoushi --role developer --text "修改代码实现测试" --objective "装配演示"   # SLIB 会话级三层装配(前缀自动取)
python3 src/hanghang/cli/main.py context assemble --session ctx-1 --unit dongjiagoushi --static-prefix "[自定义]"   # 也可显式传静态前缀
python3 src/hanghang/cli/main.py context rules --list                                        # 列出规则表(从 data/context-rules.yaml 动态加载)
python3 src/hanghang/cli/main.py context rules --match "帮我修改代码实现测试"                  # 命中测试：返回需装配哪些上下文
python3 src/hanghang/cli/main.py context validate --layer-a "[架构] | session_context_static=true" --session demo   # 缓存隔离校验(层A内容合规 + 同session签名稳定)

# M9 POC 量化验证（状态管理 vs 全量历史对比）
python3 poc/state_m9_benchmark.py --steps 50 --verbose
```

### Web 可视化控制台
启动 Web 可视化聚合面板（页面交互形态入口，纯 Python 标准库实现，无额外依赖）：

```bash
# 方式一：通过 CLI 启动
python3 src/hanghang/cli/main.py serve --port 8080

# 方式二：直接运行模块
python3 -m hanghang.web.server --host 127.0.0.1 --port 8080
```

浏览器打开 `http://localhost:8080/` 即可访问控制台页面。

> **安全提示**：默认仅监听 `127.0.0.1`（回环）。服务含状态变更接口
> （`POST /api/route` 记录运行指标、可写交接/指标数据）。若以
> `--host 0.0.0.0` 显式对外暴露，**服务启动时会打印⚠️安全告警横幅**，
> 且必须置于认证/网关之后，避免未授权访问。
>
> **指标口径说明**：`manual`（人工确认）分支若路由结果含候选岗位
> （置信度不足但已模糊命中），该岗位仍计入 `role_hits`——role_hits 表示
> "候选命中岗位"，`manual_confirmations` 单独统计人工介入次数。CLI 与
> Web POST 均按此口径记录。
>
> **数据真实性保障**：`auto_success_rate` 仅在已有路由记录时返回百分比值。
> 当累计路由数为 0（尚无任何数据）时，该字段返回 `null`（Web/CLI 显示
> "暂无数据"），**绝不伪造为 0% 或 100%**，避免误导判断。

页面聚合展示：
- **行业单元总览** — 14个行业/岗位/能力/入口
- **路由测试** — 输入一句话意图即时路由（含自动识别/复合装配/回落人工判定）
- **能力检索** — M8 跨行业能力多维搜索
- **能力索引** — 全量能力标签 → 承接岗位映射
- **运行指标** — M7 自动成功率/复合使用率/人工介入率
- **前缀档案** — M3 各行业稳定前缀
- **交接卡** — M5 待处理交接卡
- **任务进度** — M9 编排/交接 StateCard 聚合（自动落卡的任务进度，供出口复核）

也提供 REST API（供其它形态调用 / 前端页面消费）：

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/units` | GET | 行业单元总览 |
| `/api/route?text=...` | GET | 意图路由识别 |
| `/api/route` | POST | 意图路由识别（JSON body） |
| `/api/search?kw=..&mode=..` | GET | 能力索引搜索 |
| `/api/index` | GET | 全量能力索引 |
| `/api/metrics` | GET | 运行指标 |
| `/api/industry-db` | GET | M11 行业分区定义库（分区表+职业表+覆盖率+自检，只读） |
| `/api/handoffs` | GET | 待处理交接卡 |
| `/api/prefixes` | GET | 稳定前缀档案 |
| `/api/state` | GET | M9 编排/交接状态卡聚合（任务进度，只读） |
| `/api/session?id=..` | GET | M9 单会话编排快照 + 续传锚点（只读；RFC-ECO-01 阶段4·轮询拉取形态） |

> 设计原则：前端/页面只做「聚合 + 可视化」，底层能力通过 REST API 与 CLI 双形态暴露，为将来多调用形态（生态整合）预留。

### 岗位卡渲染与校验

```bash
# 改完 data/role-profiles 或 data/workflow-templates 后重渲岗位卡
python3 scripts/gen_rolecards.py --from-kwp vendor/upstream/knowledge-work-plugins
# CI 用：校验已提交岗位卡是否与数据一致（不一致退出码 1）
python3 scripts/gen_rolecards.py --check
```

### 运行测试

**推荐：变更感知测试**（本地/PR 通用，只跑本次变更影响到的测试，避免频繁全量）：
> 前置：先安装依赖 `pip install -r requirements.txt`（变更感知内核 `ca-plan.py` 依赖
> `pyyaml`，CI 由 `.cnb.yml` 兜底安装；本地直跑前也需先装，否则会 `ModuleNotFoundError`）。
```bash
bash scripts/change-aware-test.sh                # 自动按 git 变更选测试
bash scripts/change-aware-test.sh --dry-run      # 只看会跑哪些，不执行
bash scripts/change-aware-test.sh --all          # 强制全量（main 合并门禁/发布兜底）
bash scripts/change-aware-test.sh --no-cache     # 忽略结果缓存，强制重跑本次选中用例
bash scripts/change-aware-test.sh --purge-cache  # 清空结果缓存
```

> **通用增量测试机制（v4）**：`scripts/change-aware-test.sh` + `scripts/ca-plan.py` 是一套
> **仓库/语言无关**的变更感知测试基建（python 内核，与仓库/CI 的 python 生态天然同源，
> 复制到任意仓库 `scripts/` 即用，无需额外 node 运行时）——
>
> 1. **自动依赖推断选测试（公交攒批）**：不再人肉维护“源码→测试”硬编码映射表。
>    内核静态解析每个测试文件 import/require 的本地模块，反向建立依赖索引；
>    源码变更 → 只跑「引用它」的那批测试；测试文件变更 → 只跑它；一批一次跑完。
> 2. **结果指纹缓存防重复全量**：覆盖指纹 = hash(测试文件 + 其 import 的源码)。
>    源码与测试均未变化且上次已 PASS → 命中缓存跳过，沿用上次结果，不再重复全跑；
>    任一变化指纹即变、必然重跑，不会漏测。
> 3. **基建/CI 文件不误触发**：`scripts/`、`.cnb.yml`、锁文件等工具变更若无可对应测试
>    则视为“非业务变更”，不会因脚本自身改动而强行全量回归。
> 4. **纯文档变更自动跳过**；未知源码变更仍保守全量兜底，绝不全靠缓存漏测。
> 5. **工具自身改动也自校验（防回退）**：`ca-plan.py` 依赖推断内核若失效会静默放行缺陷，
>    故每次 CI 都会跑 `python3 scripts/ca-plan-selfcheck.py`——用固定 fixture 断言
>    “改动 `engine/router.py` 等核心文件必须选中 `test_router` 等直测文件”。
>    复制内核到他仓改 import 解析时，此护栏可即时暴露“漏选/回退”。
>    （`.ca-plan.json` 为瞬时落盘文件，已加入 `.gitignore`，异常崩溃残留不入库。）
>
> 可选配置 `ca-test.conf`（或环境变量 `CA_*`）可覆盖源码根 / 测试 glob / 静态映射，
> 为无 import 的 bash 脚本测试等提供兜底规则。缓存目录默认 `.testcache`，
> 流水线通过 `CA_CACHE_DIR`（兼容 `HH_TEST_CACHE_DIR`）+ `cache:` 卷持久化跨流水线复用。

**测试覆盖与冗余审计**（校准：哪些源码缺鉴定、哪些用例高度重复）：
```bash
python3 scripts/audit-tests.py        # 全仓覆盖矩阵 + 冗余/缺口报告
python3 scripts/audit-tests.py --by-file
```

**全量回归**（main 合并门禁 / 发布前兜底，绕过缓存全跑）：
```bash
python3 scripts/run_all_tests.py
```

亦可单跑某个测试文件：
```bash
python3 tests/test_web.py             # Web 可视化面板 API
python3 tests/test_router.py          # 路由引擎
python3 tests/test_registry.py        # 注册表与元数据
python3 tests/test_handoff.py         # 交接总线
python3 tests/test_data_driven.py     # 数据驱动 + 复合边界 + 交接自动集成
python3 tests/test_review.py          # 评审机制
python3 tests/test_industry_expansion.py  # 行业扩展 + M8 能力索引增强
python3 tests/test_batch_persist.py   # M9 批量/延迟落盘
python3 tests/test_state_manager.py   # M9 状态管理层（StateCard/折叠/层级提交）
python3 tests/test_state_tree.py      # M9 秘书长多级树 + 主链路集成
python3 tests/test_state_ownership.py # M9 秘书并发归属与冲突仲裁
python3 tests/test_state_arbiter.py   # M9+ 版本化冲突仲裁与审核
python3 tests/test_state_cli_e2e.py   # M9 × CLI 全链路联调回归
python3 tests/test_dongjiagoushi_routing.py  # dongjiagoushi M1 外挂路由验证
python3 tests/test_context_m10.py     # M10 上下文装配器（防冗余规则表/三层装配/缓存保护）
python3 tests/test_cli_context.py     # M10 × CLI context 三子命令（assemble/rules/validate）
python3 tests/test_slib.py          # SLIB 会话级行业绑定（SessionBinding/SessionBoundRouter）
python3 tests/test_industry_db.py   # M11 行业分区定义库（职业↔岗位双向对齐/产值口径/扁平表导出）
python3 tests/test_occupation_catalog.py  # 职业分类大典参考表（编码/映射外键/两个分母不混读）
python3 tests/test_global_framework.py  # 全球分类框架（ISCO-08 参考表/四根轴索引/副证缺失不静默）
python3 tests/test_rolecard_m11.py  # M11.1 岗位画像层（渲染/就绪度/模板合并/路由加权/上下文注入）
python3 tests/test_chain_m11_1.py   # M11.1 利益链条归一（公司不落库/类目索引/叫法收敛/岗位引用）
python3 tests/test_classstore_m11_2.py  # M11.2 词表目录化（域文件→DDL/数据字典一致性）
python3 tests/test_roledb_m11_3.py  # M11.3 实库（建库回读/双方言 DDL/列表型字段一行一条）
```

## 数据文件

- `data/industry-register.yaml` — 行业单元注册声明（M2 数据源）
- `data/unit-index.yaml` — 跨行业单元索引（M8）
- `data/industry-occupations.yaml` — M11 岗位表（原子单位：唯一编号 `OCC-######` + 稳定 slug，**不存归属字段**）
- `data/occupation-memberships.yaml` — M11 归属边（岗位 × 视角 × 轴 × 权重；一个岗位可被多个视角同时引用）
- `data/industry-partitions.yaml` — M11 行业分区表（聚类依据/付费方/供给结构/产值口径）
- `data/reference/occupation-catalog-2022.yaml` — 《职业分类大典（2022 年版）》参考表（8 大类/79 中类/449 小类/1636 细类，只读）
- `data/reference/occupation-gb-map.yaml` — 职业 ↔ 大典细类编码的人工映射（宁缺勿错）
- `data/reference/occupation-catalog-isco08.yaml` — ISCO-08 国际职业分类参考表（10/43/130/436 + 1931 条官方示例职位名，只读）
- `data/reference/classification-sources.yaml` — 四根轴（职业/行业/税收/产出）分类体系索引：各标准规模、维护方、已接/待接
- `data/coverage-target.yaml` — 行业岗位覆盖**目标全集**（分母）；与已注册单元比对得到整体目标与当前覆盖率的进度（v0.3 起包含 `evaluated` 分区：目标全集回答"哪些人群必须看得见"，不等于"都要建单元"）
- `data/prefix-archive.json` — 稳定前缀档案（M3，含全部14单元，版本化提交）
- `data/metrics.json` — 运行指标（M7，自动生成）
- `data/state/` — 状态卡 JSON（M9，自动生成）
- `data/context-rules.yaml` — M10 上下文装配触发规则表（声明式）
- `data/rolecard-schema.yaml` — M11 岗位画像数据契约（六维字段/能力评分维度/就绪度权重与分档）
- `data/role-profiles/<unit>.yaml` — M11 岗位画像**人工基线**（六维评估，人写慢变）
- `data/workflow-templates/*.yaml` — M11 通用工作流模板（岗位只写 override）
- `data/rolecards/<unit>.yaml` — M11 岗位卡**渲染产物**（`scripts/gen_rolecards.py` 生成，勿手改）
- `data/industry-classes.yaml` — M11.1 行业类词表（类目 + 索引方案 + 叫法别名 + 公司形态标记）
- `vendor/upstream/knowledge-work-plugins/` — 上游只读快照（Apache-2.0，仅离线渲染参考）
- `data/arbitration/` — 冲突仲裁票据 JSON（M9+，自动生成）


## 行业分区定义库（M11）

**岗位原子化，分类是筛选器。** 解决"行业靠命名堆叠、改名就漏就重"的问题：

- **岗位表** `data/industry-occupations.yaml`：原子单位，唯一编号 `OCC-######` + 稳定 slug，
  **不写"我属于哪个分区"**。178 条（基线 165）是**能被行业单元承接的收敛基线**，不是职业全集；
  全集在 `data/reference/occupation-catalog-2022.yaml`（大典 1636 个细类，带国标编码），
  补岗位时照表挑、用 `gb_code` 挂回标准，别现编名字。
- **归属边** `data/occupation-memberships.yaml`：岗位和视角之间的关系全在这里，
  带轴和权重。**一个岗位可以被任意多个视角同时引用，权重不必相加为 100**——
  0.6+0.5 不是错误，是"两件活都真干"。想只看主要归属就 `--min-weight 0.5`。
- **分区表** `data/industry-partitions.yaml`：只写清"为什么聚类"（聚类依据 / 付费方 /
  供给结构 `provider_mix` / 产值口径 `gdp_cny`）。成员是**按视角筛出来的结果**，
  不是"归属于它的东西"；分区不存清单，岗位不存归属，两边永远不会分叉。

  单值归属是硬分类，有三个躲不掉的毛病：丢信息（无法表达跨行业）、被管理绑架
  （改分区就得批量改岗位）、假装确定（现实里大多数岗位本来就跨行业）。
  所以分类只当筛选器用：`industry filter --partition X --provider ai --min-weight 0.5`。
- **聚类粒度**：付费方与交付方式同一件事才合并，否则必须拆。口译/笔译、直播/电竞、
  健身/赛事三组已按这条拆开；拆分分区没有独立产值口径就留 `null`，不按比例切一份
  （切一份等于同一批钱算两遍）。旧折叠 id 有回归测试盯着，不许复活。
- **三层递进**：职业 → 分区（聚类）→ 单元（真正能被路由）。`status` 区分
  `covered` 已建 / `pending` 待建 / `evaluated` 评估后不建（不计分母，避免永久缺口）。
- **不引入外部数据库，但备好交接**：yaml 是权威源（可评审、可回滚、可被知识库切片），
  `industry export` 一键生成 14 份产物：`industry.sqlite` + 九份 csv（含六口径账、资金流账、官方对表、生产法、战略视图）
  + json 给 BI/知识库直接吃，
  `00-schema.sqlite.sql` / `00-schema.postgresql.sql` / `10-data.sql` 是「买好服务器直接建库」用的
  双方言 DDL 与与方言无关的数据 SQL，拿到不跑 Python 也能装。详见 `docs/industry/industry-db-import.md`。
- **产值口径诚实，且必须同列**：`gdp_cny` 是量级参考，用于排序定权重；无市场口径的分区
  （行政办公/政务公共/国际事务）**刻意留 `null`**，绝不填 0 冒充数据。数字旁边永远跟着
  `gdp_kind`（增加值/总产值/营业收入/市场规模/成本总额/GMV/none）——**只有同口径才能相加**：
  可对外引用的只有增加值口径的 55 万亿，旧版那句「合计 181.7 万亿」把 GMV、物流费用、
  建筑业总产值和制造业增加值加在了一起。
- **双向自检**：`industry check` 跑 26 条校验（唯一编号/主键唯一/状态枚举/归属边悬空/权重越界/
  同边重复/职业↔岗位对齐/岗位骨架反查/大典映射外键/供给结构对账/产值口径标签/六口径落点/
  口径互推/资金流对账/官方基准逐年对表/生产法去重/行业战略视图/数据源存在），其中三条专守"分母被悄悄缩小"
  的暗沟——分区 id 写重、`status` 拼错、标了 `covered` 却没登记岗位，这三种错不会让覆盖率变红，
  只会让它变好看。明确**不校验**"归属是否唯一"：那是伪命题。
  条数只有一处来源（`IndustryDatabase.VALIDATE_CHECK_COUNT`），README、文档标题、
  CLI 回执都读它——上次这数被手抄三份，抄成了 15/17/18 三个数，评审纠了两轮。
  流水线在 PR 测试、合并门禁、main 全量回归三处都会跑它，数据漂移不靠自觉。

## 行业规模账：六口径，谁有数谁说话

**一个大行业不该因为「产值没统计」就整体隐身。** 产值（增加值）是最难拿的一格——
全国只有约 20 个门类有官方增加值，细分行业往往没有独立统计。但同一个行业在别处
留着痕迹：利润总额、资产总计、上市板块市值、从业人数、能耗水耗。

所以口径不是「更精确的同一个数」，而是**同一批钱的六个侧面**：

| 口径 | 回答什么 | 谁最常给 |
|---|---|---|
| `gdp` | 一年新增多少价值 | 统计局分行业增加值 |
| `employment` | 多少人在干 | 统计年鉴从业人数 |
| `profit` | 兜里剩下多少 | 规上企业利润总额 / 上市公司年报 |
| `asset` | 压着多少钱 | 规上企业资产总计 / 资产负债表 |
| `valuation` | 市场给多少钱 | 上市板块总市值 / 一级市场估值 |
| `resource` | 吃掉多少实物 | 能源消费/用电/用水/原料（保留实物单位，不折成钱） |

```bash
python3 src/hanghang/cli/main.py industry scale            # 41 个分区 × 六口径落点
python3 src/hanghang/cli/main.py industry scale --partition manufacturing
python3 src/hanghang/cli/main.py industry scale --gaps     # 只看全空分区 + 逐格原因
```

当前 **41 个分区没有一个全空**：看清大半（≥4 个口径）19 个，至少一面可见 22 个。
`admin-office`（行政办公）只有就业一格——它就是企业内部职能，没有独立产值/利润/资产，
这不是缺数据，这是行业特征；`missing` 里逐格写着这句话。

三条规矩（与 `gdp_cny` 同源）：**没有口径就不填数字**（`null` ≠ 0）；
**不重复存**（`gdp`/`employment` 从 `partition` 现读，账本不抄第二份）；
**缺格必须写原因**（说不出总量又不说什么缺 = 保证会漏）。

## 资金流守恒账：钱不会凭空生灭

只列「某个行业产了多少值」，一定会漏——钱从哪来、经谁的手、最后沉在哪里，
一条链上任何一环没画，汇总出来的总额就是假的，而且**错得看不出来**（每个数都对，
加起来不对）。所以这里做**双边记账的资金流量账**：

```
sector-enterprise → sector-household   wage         64.0 万亿   （劳动报酬）
sector-household  → sector-enterprise  consumption  47.0 万亿   （居民消费）
sector-enterprise → sector-government  tax          19.7 万亿
sector-government → sector-household   transfer     10.0 万亿
sector-enterprise → pool:manufacturing allocation   待补        （份额切分，规则未定）
```

三条不变式，缺一条这套账就变成自说自话：

1. **双边记账**：每条 flow 都是 `from → to`。所以「全局流入 ≡ 全局流出」是**恒等式**，
   不是校验点——把它当校验点只会得到一句永远为真的绿灯。
2. **节点与外部口径对账**：这才是能抓漏的一条。图里画出来的边求和，必须对得上
   居民可支配收入、一般公共预算收入这类权威总量。偏差超 10%（资金流量表与分项
   汇总的固有口径差）即报「还有流向没画出来」。
3. **没有对账口径，就必须登记未观测流向**：说不出总量、又不说什么缺，等于保证会漏，
   而它会静默通过。`unobserved` 就是逼着把这句话写下来的字段。

```bash
python3 src/hanghang/cli/main.py industry money                       # 全景：头寸 + 对账 + 明细
python3 src/hanghang/cli/main.py industry money --node sector-household
python3 src/hanghang/cli/main.py industry money --kinds                # 资金流类型及条数
```

当前：5 个机构部门全部对账闭合，8 个行业池的份额切分「路径已知、数额待补」
（`amount_cny: null` 而不是 0——编一个数填上比留空坏得多，后面所有人都会拿它当真）。
两处**已知差额**写在 `leaks` 里并解释清楚：政府性基金与土地出让收入 8.6 万亿、
影子银行表外往来 3.5 万亿。有差额可以，不解释不行。

## 官方口径逐年对表：`high` 不再是自我声明

`gdp_confidence: high` 原先谁都可以写，没人能证明。现在它是**可核对**的：
每个分区接一份官方基准（同口径、同年份、有出处），对完账 `high` 才成立。

```
benchmarks  17 个官方基准，逐年 series（16 个有两年以上，够算同比）
links       14 个分区接了官方口径
unlinked    27 个分区按组说明为什么没有可比口径（说不出为什么 = 永远没人验）
```

三种关系只有三种：`equal` 比偏差、`envelope` 比上界、`incomparable` **只登记不相减**。
最后一种不是免责出口——它必须写 `reason`，且该分区不得标 `high`。
软件业务收入 6 万亿对信息服务业增加值 5.5 万亿就是这种：收入必然大于增加值，
相减得到的"差额"没有经济含义。写清楚，比装作能比更有用。

机制一上线就抓到自己三处错：一个基准多写一个零（88 万亿 vs 8.8 万亿）、
两个分区凭印象标了 `high`。第一处单看是对的，只有和分区一撞才现形。

但**"对上"还不够**，还有个更隐蔽的坑：每个基准必须写 `origin`（怎么来的）。
只有逐表抄自公开统计表的（`published`）能给 `high` 背书；由分区估算**反推**出来的
（`backfilled`）会让对表变成循环论证——自己和自己比，永远 0% 偏差，
那得到的是一致地错，不是一致地对。这条规则又抓出 4 个假 `high`，
全仓现在只剩 4 个，都有公报原值背书。

## 投入产出：切分不重复计的规则

上一轮卡在那句「8 个池的份额全待补，卡点不是拿不到数，是拿了会重复计」。
答案就是生产法恒等式：

```
总产出 = 增加值 + 中间投入
```

部门层总额是**增加值性质**，而分区手里的常常是 GMV（平台两头计价）、
营业收入（含中间投入）、总产值（含分包重复报量）。拿这些去切，切出来的份额
必然虚高，而且虚高得看不出来——每个数都抄对了。

所以锚点只有两条合法路径：本来就是增加值口径，或者有 `va_ratio` 能折算。
**没有 `va_ratio` 就不许切**，也不许用行业平均兜底（那是看起来合理的错数）。

```
账户 35 个：恒等式闭合 1 / 只够一端 8 / 还没有落点 32
行业池 8 个：可切 2 / 不可切 6

建筑业 31.6 万亿 = 增加值 8.6 万亿 + 中间投入 23.0 万亿   va_ratio 0.272
制造业 增加值有、总产出没有 —— 这就是「33 万亿怎么切到 40 万个规上企业」卡住的真实原因
```

顺带钉住一个一定会踩的坑：`allocation` 是**备忘边**（`memo: true`）。
制造业 33 万亿本就含在企业部门那 110.5 万亿里，计入流出会让企业部门凭空多出
41 万亿，对账爆红而两条记录各自都对。memo 边不参与头寸与对账，只在
「这个行业的钱是哪一段」里出现。

```bash
python3 src/hanghang/cli/main.py industry baseline        # 逐年对表全景
python3 src/hanghang/cli/main.py industry io --pools      # 哪些行业池能切
python3 scripts/gen_data_inventory.py --check             # 盘存清单不许过期
```

**东西都在哪**：`docs/industry/data-inventory.md`（生成物，含权威源/结构产物/
导出产物/库内行数四段 + 平台路径），改了数据忘了重跑会被 CI 拦下。

## 行业战略视图：粒度只到岗位，剩下的交给 AI

前面几本账全在回答「多少钱」：产值多少、就业多少、利润沉在哪、钱流向哪、会不会重复计。
但没有一句回答「**这钱为什么在这、拿什么去挣**」。缺这一层的后果很具体。

AI 被派到「建筑工程-造价员」岗位上，它知道要算量，但不知道这个行业的利润不在算量，
而在增项与材料差（31.6 万亿产值里只有 8.6 万亿是新增价值，va_ratio 0.272）——
于是它会认认真真把一个不赚钱的环节做到极致。这不是能力问题，是没人告诉它行业长什么样。

所以每个分区补一份战略视图，**粒度红线是只到岗位和角色**：

```
价值链     规划设计 → 总包施工 → 专业分包 → 材料与设备 → 竣工运维与更新
议价位置   总包居中：对上游压价、对下游担责，产值大但增加值薄
利润池     材料与设备 —— 中间投入的集中落点，规模最大但被账期吃掉
           规划设计   —— 真正议价的一环，改一张图改的是全案成本
杠杆       资质、垫资能力、账期管理
驱动       基建与城市更新、装配式与BIM、地方财政支付能力
风险       应收账款与垫资、安全事故终身追责、低价中标
AI 站得住  算量与清单编制、图纸审查与碰撞检查、投标文件与施工方案初稿
AI 站不住  签字与验收、投标决策与报价、安全责任
AI 边界    AI 出量与方案初稿，签字盖章和终身追责必须由人到场担
人管什么   接哪个标、报什么价、工期与质量底线
AI 补什么   按部位补清单规则、按工法补方案模板
岗位落点   bidding_specialist、cost_estimator
```

**再细的东西不写。** 具体工序、话术、判定标准、KPI 一律不进数据——那是 AI 上到
那个岗位、认清职责之后自己充当角色时补的。写死在数据里的那一版，一定比市场慢半年，
而且再没人回来改；AI 拿到它只会照着做，不会照着判断。**我们是分工的**：
人写判断，AI 按判断干细活。

这条红线是硬校验（第 26 条）：字段里出现 `steps`/`sop`/`prompt`/`kpi`/`persona` 即报。
另外两条也一起守——战略层**不许重复存金额**（`cny`/`amount`/`gdp` 一律回 partition
和六口径账，同一件事存两份迟早对不上），`role_focus` **必须落在本分区真实岗位上**
（已建单元对 `unit-index` 的 roles，待建分区对 `planned_roles`；落不到岗位的战略
就是一句没人负责的口号）。

```bash
python3 src/hanghang/cli/main.py industry strategy                     # 41 个分区的战略全景
python3 src/hanghang/cli/main.py industry strategy --partition construction-eng
python3 src/hanghang/cli/main.py industry strategy-gaps                # 哪一段空着、为什么空
python3 src/hanghang/cli/main.py industry io --inputs                  # 中间投入构成还缺什么
```

顺带把上轮留下的第 3 条也接上了：中间投入构成 0 个分区有，卡点不是数据源，
是**接了没有落点**。现在 `industry io --inputs` 直接给一张清单——每个分区缺什么口径、
该去哪张表要、补进来支撑哪个判断，`io-input-plan.csv` 与 JSON 的 `input_plan` 同一份。

**国际口径**：职业轴再接一层 ISCO-08（ILO，436 细类 + 1931 条官方示例职位名），
行业轴与税收轴的口径与接法见 `docs/industry/global-framework.md`。
外部标准一律只读、不进 coverage 分母——它们是"还能挑多少"，不是"还欠多少"。

`coverage` 的岗位基线现在**优先取职业库**，`coverage-target.yaml` 只作兜底，
避免两处手写岗位各自漂移。详见 `docs/industry/industry-partition-db.md`。

## 行业覆盖进度与多渠道搜集

平台以 **coverage 进度** 统一回答「整体要覆盖多少行业/岗位、当前覆盖到多少」。

- **目标全集 = 分母**：`data/coverage-target.yaml` 声明应覆盖的行业单位清单及各自标岗位。
- **当前覆盖 = 分子**：由已注册单元自动判定（按行业名对齐 unit-index），无需手工维护。
- **覆盖率**：`coverage` 命令输出 行业覆盖率 与 岗位覆盖率 两张进度表，并可按缺口（`--gaps`）列出待补行业及建议搜集渠道。

`coverage-target.yaml` 每个待补行业均声明了 `priority`(优先度) 与 `channels`(建议搜集渠道)，用于引导通过各渠道（招聘岗位库、行业协会目录、职业分类大纲、服务机构目录、用户真实诉求沉淀等）充分搜集岗位/职业/行业后逐步建单元补齐。新增目标行业只需在 `targets` 追加一条声明即可自动纳入进度统计，无需改代码（数据驱动）。

### 补全职业的四个尺子（别压成一个判断）

补职业时最容易犯的错，是拿"**能不能向终端用户直接收费**"当唯一过滤器。一旦这么筛，
会同时丢掉两类人：口径没扫到的（主播/陪玩挂在互联网信息服务下，不独立成行），
和付费方不是终端用户的（军人/消防/矿工，财政或项目款付费）。两种错原因完全不同，
所以现在拆成四个各管各的问题：

| 尺子 | 回答什么 | 字段 |
|---|---|---|
| 职业 | 这个人在干什么活 | `industry-occupations.yaml` 一条记录 |
| 承接通道 | 怎么和付费方接上 | `access`：`paid_direct`(缺省) / `non_market`(财政) / `org_internal`(雇主预算) / `household`(家庭无酬) |
| 视角 | 在哪根轴成立 | `axes`：职业/行业/税收/产出，**一个分区可被多根轴引用** |
| 单元 | 要不要建执行体 | `status`：`covered` / `pending` / `evaluated` |

**`evaluated` 不等于忽略**：职业照样登记、通道照样统计、就业人数照样计入产出轴，
只是不从数字员工这条产品线建单元。"该不该被分析"和"要不要建 AI 单元"是两件事 ——
采矿工的画像影响市场，值得存；AI 能不能替他下井作业，是另一个问题。

## 复合装配的边界规则（评审补强① 已落实）

同一行业多岗位复合时，自动按**依赖序**排列（如 `product → architect → developer → reviewer`）。
岗位间通过交接卡传递产物，不互相污染记忆（`role_isolation: handoff_card_only`）。

```
产品规划 → 架构方案 → 编码实现 → 评审
（前一岗位产物作为下一岗位输入，各自session独立）
```

## 文档索引

- 顶层架构: `docs/architecture/ARCHITECTURE.md`
- 需求基线: `docs/architecture/通用能力-需求澄清基线.md`
- 行业分区定义库(M11): `docs/industry/industry-partition-db.md`
- 职业分类大典参考表: `docs/industry/occupation-catalog.md`
- 全球分类框架（四根轴/国外体系/接法）: `docs/industry/global-framework.md`
- 单元接入规范: `docs/industry/register-spec.md`
- 首行业单元外挂验证(dongjiagoushi × M1): `docs/industry/dongjiagoushi-m1-routing.md`
- 行业使用说明（面向 Agent，按行业）: `docs/industry/units/INDEX.md`
- 岗位画像层(M11.1): `docs/architecture/M11-岗位画像层.md`（含 §9 利益链条归一）
- 词表目录化与云仓(M11.2): `docs/architecture/M11.2-词表目录化与云仓数据库.md`
- 实库落地(M11.3): `docs/architecture/M11.3-实库-岗位与行业类落库.md`
- 功能特性交付索引: `docs/feature-delivery.md` / `-v2.md` / `-v3.md`(M9) / `-v4.md`(M10) / `-v5.md`(M9+仲裁) / `-v6.md`(行业v3) / `-v7.md`(SLIB) / `-v8.md`(M9进度可视化) / `-v9.md`(ContentArchive归档) / `-v10.md`(会话续传快照) / `-v11.md`(行业v4·coverage校准) / `-v12.md`(行业分区定义库) / `-v13.md`(补全与视角分离·承接通道) / `-v14.md`(岗位画像层·六维评估/就绪度/实库)
- POC验证记录: `poc/`

## 自动评审机制

本仓库已同步自动代码评审闭环机制（参考自 dongjiagoushi / youxikaifaxilieagent）。

### 机制流程

```
PR 提交 → 测试信号灯 → NPC 代码审查 → 需修改？→ CodeBuddy 自动修复
                                              │           │
                                              │ 不需要     │ 修复后触发下一轮
                                              ▼           ▼
                                        评审通过 → 合并门禁 → 自动合并
                                              │
                                              ▼
                                        main 合并 → 全量回归
```

### 触发事件

| 事件 | 动作 |
|------|------|
| `pull_request` | 自动跑测试 + NPC 代码审查 + 修复闭环 |
| `pull_request.mergeable` | 评审通过后自动合并 |
| `pull_request.changes_requested` | CodeBuddy 自动修复 |
| `pull_request.comment@npc` | 手动召唤兜底（只写全限定名 `@仓库路径(CodeBuddy)`） |
| `main.push` | 全量回归 + 知识库更新 |

### 评审相关文件

- 流水线配置: `.cnb.yml`
- NPC 角色: `.cnb/settings.yml`
- 评审闭环规则: `docs/评审修复闭环护栏.md`
- 测试脚本: `scripts/`
