# 功能交付 v14 · 意向兑现：孤立职业归零（M11 第四轮）

**来源**：用户在 PR #29 的原话 —— "好了，有额度了，继续做吧"。

上一轮把 CI 的红查清楚了（Prepare 阶段配额不足，一行测试都没跑），代码侧一直是绿的。
额度恢复后，本轮做的是**唯一还剩的实质缺口**：8 个职业的归属只写了一句话。

## 一、问题：8 个职业只在 `note` 里许愿

上一轮为了堵住"意向只活在注释里"，加了 `pending_partition` 字段（第 18 条校验）。
但那只是把许愿**变成可校验的数据**，并没有真的兑现：

```yaml
- {id: nurse, ..., pending_partition: healthcare, note: "护理是医疗一线，但线下交付"}
```

后果是三重的，而且都不会让绿灯变红：

- 任何视角里都看不见这几条 → 不算成员；
- 供给结构分母漏掉它们 → `provider_mix_n` 停在 170 而不是 178；
- 覆盖率分子也不含它们 → 但覆盖率显示 100%，看不出漏了谁。

## 二、改法：许愿换成边

8 个职业全部挂上真边，`pending_partition` 清空，`free_occupations` 从 **8 → 0**：

| 职业 | 挂到 | 说明 |
|---|---|---|
| `qa-engineer` 测试工程师 | `dongjiagoushi` | 单建测试岗前先挂 `reviewer` |
| `sre-devops` 运维/SRE | `dongjiagoushi` | 环境与部署归 `developer` |
| `algorithm-engineer` 算法工程师 | `data-analytics` 0.6 / `dongjiagoushi` 0.4 | 横跨两侧，用权重表达 |
| `game-artist` 游戏美术 | `game-dev-unit` 0.7 / `design-visual` 0.5 | 生产链与技能栈各占一边 |
| `patent-agent` 专利代理人 | `legal-services` 0.8 / `research-academic` 0.3 | 法律为主、科研转化次之 |
| `auditor` 审计师 | `finance-accounting` | 独立签字主体，岗位名复用 `accountant` |
| `nurse` 护士/护理 | `healthcare` | 线上窗口复用 `health_consultant` |
| `translator` 翻译/本地化 | `translation` | 笼统口径，岗位名先挂 `subtitle` |

两条口径刻意写死在这里：

1. **挂到已建单元的边一律复用该单元已有的岗位名**，不为这几条边临时造岗位。
   单建岗位是单元侧的决定；数据侧编一个名字，只会让路由永远命中不了（比不挂更坏）。
2. **`provider_mix` 声明值随之按实测回填**。新成员进来，实测分布必然移动，
   对账机制先报偏移（`dongjiagoushi` 偏 38pt、`translation` 偏 25pt…）再据实回填。
   这不是手改数字凑绿，是这套对账本来该走的路。

## 三、副作用：校验器一次抓出 14 处

第一版边写完，`industry check` 立刻红了 14 条——**一条都不是误报**：

```
- 职业 qa-engineer 挂在已注册单元 dongjiagoushi，但未填 unit_role
- 职业 auditor 的 unit_role=auditor 不在单元 finance-accounting 的岗位中
- 分区 translation 的 provider_mix.ai 声明 0.0% 与实测 50.0% 偏差 50pt
```

第 9 条（已建单元必须有岗位名）和第 11 条（声明 vs 实测）在这一刻同时生效。
说明上一轮那几条校验不是纸面防守，补数据的时候它真的会拦人。

## 四、测试：把"补全完成"当成回归前提就错了

三条既有断言在孤立职业归零后失效了（`StopIteration`、`0 < free`、写死成员数）。
修法不是把数字改大，而是**换成不依赖"现实里还有人掉队"的写法**：

- `test_cli_occupations_unassigned_is_not_whole_library`：造一个孤立职业验筛选口径；
  现实数据里 CLI 必须明确说"无匹配职业"，而不是把全表端出来冒充未挂；
- `test_note_only_intent_is_now_explicit_data`：改成断言 `free == 0`，
  再造一个掉队的验明细出口没变成死代码；
- `test_export_flat_tables`：`row == 5` → 与 `axis_view.memberships` 实际条数对齐
  （写死数量会随补登记漂移）；
- 新增 `test_previously_free_occupations_are_now_linked`：8 条边逐一验在，
  且已建单元的那 7 条必须带真实岗位名。

## 五、现在的数字

```
分区: 14/36 已建单元 (38.9%)   另 5 个不建单元(不计分母)
职业登记: 165/165 基线 (100.0%)   全量登记 178 个
视角边: 186 条   孤立职业: 0   被多个视角同时引用的岗位: 7
供给结构(178 个已挂分区职业实测): AI 8.4% / 混合 38.8% / 纯人 52.8%
承接通道(178 个实测): paid_direct 89.3% / non_market 9.6% / org_internal 0.0% / household 1.1%
大典映射: 111/178 (62.4%)
```

> 供给结构从 8.3/36.7/55.0（n=169）变成 8.4/38.8/52.8（n=178）是**分母变大**，
> 不是口径改了：补进来的 8 个职业里 7 个是 `human`，所以纯人比例反而降了——
> 因为原来漏算的那批本来就在"人比 AI 更吃重"的位置上。

## 六、复验

- `python3 scripts/run_all_tests.py` → **30 个测试文件全绿**，CLI 冒烟通过
- `industry check` → 19 条校验 / 41 分区 / 178 职业，双向对齐无缺口，rc=0
- `industry occupations --unassigned` → "无匹配职业"
- `industry partitions` → 孤立职业 0，供给结构 n=178
- `GET /api/industry-db` → 200，`problems` 为空

## 七、留在桌面上的

1. **多归属的权重是人工判断**（0.6/0.4 这种）。目前只有 7 个职业有多视角，
   权重靠经验；要不要引入"工时占比"之类的外部口径，需要拍板。
2. **单建岗位**：测试/运维/审计/护理/专利这几条现在借别的岗位名跑。
   要真让路由命中它们，得在对应单元里各建一个 role——那是单元侧的活，不在数据侧做。
3. 二级聚类（制造业拆电子/机械/化工）和 `gdp_cny` 逐年校准，仍未动。
