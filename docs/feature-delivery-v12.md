# 功能交付 v12 · M11 行业分区定义库

**来源**：ISSUE #19（进度和目标掌控）后续诉求 ——
"把目前各个行业的分区形成定义表/数据库；先把都包含什么行业形成表；
列出人类和 AI 存在的行业/职业、付费方与服务提供者/生产力提供者；
有市场产值列表；**把他们聚类，这才形成行业**——
之前的职业才是真正解耦合的单目标，不会被命名方式影响和缺漏。"

> **本文是 v12 交付时点的快照，数字不会随分支继续演进。**
> 现状一律以 `python3 src/hanghang/cli/main.py industry check` 的实跑输出为准，
> 正文不抄第二份数字 —— 抄一份就多一处会过期的锚点（这里原先就抄成了 177/164）。

## 交付内容

| 项 | 位置（v12 时点数，非现状） |
|---|---|
| 职业表（最小单目标，稳定主键） | `data/industry-occupations.yaml`（147 个职业，基线 139） |
| 分区表（聚类结果 + 付费方 + 产值口径） | `data/industry-partitions.yaml`（37 分区：14 已建 / 18 待建 / 5 评估不建） |
| 引擎 | `src/hanghang/engine/industry_db.py` |
| CLI | `src/hanghang/cli/industry_commands.py`（`industry partitions/partition/occupations/check/export`） |
| REST | `GET /api/industry-db`（只读，含 `problems` 自检） |
| 文档 | `docs/industry/industry-partition-db.md` |
| 测试 | `tests/test_industry_db.py`（39 项）+ `test_coverage.py`（12 项，含权威源降级）+ `test_web.py` 端点断言 |

## v12 时点进度快照（非现状）

```
分区: 14/32 已建单元 (43.8%)   另 5 个评估后不建单元(不计分母)
职业: 139/139 基线 (100.0%)    全量登记 147 个
供给结构(139 个已挂分区职业 provider 实测): AI 10.1% / 混合 38.1% / 纯人 51.8%
```

> 职业覆盖率达到 100% 是「登记完整性」达标，不等于「行业已建成单元」：
> 18 个待建分区的职业已登记并挂了 `unit_id`，但对应单元尚未建，因此
> **分区覆盖率仍只有 14/32 = 43.8%**。两个分母各管一件事，别混着看。

## 设计取舍

1. **不让分区重复存职业清单**。成员一律由 `occupation.unit_id` 反查，
   从根本上消灭"两份清单分叉"这一类脏数据。
2. **`evaluated` 状态**。评估后明确不建单元的分区（矿业、公用事业、水利海洋、
   国际组织、公共安全）不进分母，否则覆盖率永远追不满。
3. **产值留空而非填 0**。`admin-office`/`public-affairs`/`international-org`
   没有市场付费口径，`gdp_cny: null` 且 `gdp_source: 不适用，刻意留空`。
   排序时 `null` 不参与，不会把"无口径"误读成"零产值"。
4. **不引入外部数据库服务**。yaml 作为权威源；`export` 产出 sqlite + csv，
   借 CNB 制品库分发，零部署、可 diff、可被知识库直接切片。
5. **coverage 岗位基线改以职业库为准**。`coverage-target.yaml` 的 `target_roles`
   降级为兜底，避免两处手写岗位漂移；每行带 `roles.baseline_source`
   （`occupation` / `unit_roles` / `target_roles` / `stale`），兜底可见不静默。
6. **供给结构一律实测**。`provider_mix` 由成员职业 `provider` 字段统计得出，
   与「不存第二份清单」同一条立场；分区手写值降级为 `provider_mix_estimated`
   对账留档，偏差 > 25pt 由 `validate()` 报出来。
7. **分母被悄悄缩小是这类数据最危险的错**。分区 id 写重、`status` 拼成 `coverd`、
   标了 `covered` 却没登记职业——三种错都不会让覆盖率变红，只会让它变好看。
   `validate()` 现在有 13 条校验，其中 1（主键唯一非空）、2（状态枚举）、
   6（covered 无成员）专门守这三条暗沟；第 8 条守"职业挂到单元 id 而不是分区 id"
   ——这类数据在 `members_of()` 反查里永远查不到，必须在成员循环之外独立扫描。
8. **索引不能过期**。`partition()` 走的是加载期 id 索引，动态追加/替换记录后
   会返回 `None`（详情页永远"未找到"）或旧对象；现在按列表指纹自动重建，
   重复 id 显式保留首次出现并 `warning`。

## 验证

- `python3 tests/test_industry_db.py` → 39 项通过
- `python3 tests/test_coverage.py` → 12 项通过
- `bash scripts/change-aware-test.sh` → 24 个测试文件全部通过（含 CLI 冒烟）
- `python3 src/hanghang/cli/main.py industry check` → 37 分区 / 147 职业，双向对齐无缺口
- `.cnb.yml` 已接入 `industry check`：PR 测试阶段、合并门禁、main 全量回归三处都会跑，
  数据漂移不再靠自觉；`main.push` 另跑 `industry export` 校验 4 个扁平表能产出

## 后续（待拍板）

- 待建 18 个分区的职业需按渠道补齐（每个分区已登记 `channels` 数据来源）。
- 二级聚类：制造业/建筑工程这类大分区目前只做一级，需要按子行业再聚一次。
- 产值口径校准：当前为量级估算，需要用国家统计局分行业增加值/营业收入逐年对齐。
