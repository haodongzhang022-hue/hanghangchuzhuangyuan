# 行业单位接入规范（industry-register.yaml）

> 架构·总师 | 供 L1-M2 注册表抓取

## 目的
让任一基座单位（如 `dongjiagoushi`）成为「行行出状元」通用能力层的可路由单位。
各单位只需在自身仓库根放一份 `industry-register.yaml`，本层定期抓取即可接入。

## 契约字段

```yaml
unit_id: 全局唯一标识          # 建议=仓库名
industry: 行业标签             # 路由依据(如 软件研发/游戏/电商)
industry_alias: [行业别名]     # 供意图识别 L1-M1 匹配
roles:                         # 单位内可路由岗位
  - name: 岗位名
    prefix: "[稳定前缀]"
    handoff: relay|direct      # 交接协议
    composite: true|false      # 是否可被复合装配
    keywords: [岗位触发词]     # 供路由识别（数据驱动，无需改代码）
entry_ref: 单位仓库地址
capability_tags: [跨界检索关键词]
register_version: 版本号
```

## 数据驱动字段说明

`keywords` 是岗位的**触发关键词**，供 M1 意图路由引擎识别。
- 各岗位应声明 3~8 个中文触发词（如架构师声明: `[架构设计, 架构方案, 架构师, 做架构, 技术方案]`）
- 新增行业单元时，只需按此规范提供注册数据即可接入，**无需修改路由引擎代码**
- 若某岗位未声明 keywords，引擎会自动从 `description` 字段中分词作为兜底

## 稳定前缀规则（核心约束）
1. **一个 session = 一个行业单位 = 一套前缀**，中途不得切换行业。
2. 各岗位前缀需**互不相同且长期稳定**，禁止同会话内突变。
3. 跨行业必须开新 session，用交接卡协议接力。

## 示例（以 dongjiagoushi 为参考单位）

```yaml
unit_id: dongjiagoushi
industry: 软件研发
industry_alias: [研发, 架构师, 软件开发, dev]
roles:
  - {name: secretary, prefix: "[秘书]",  handoff: relay, composite: true,
     keywords: [秘书, 编排, 记录, 汇总, 会议纪要]}
  - {name: architect, prefix: "[架构]",  handoff: relay, composite: true,
     keywords: [架构设计, 架构方案, 架构师, 做架构, 总体设计]}
  - {name: developer, prefix: "[开发]",  handoff: relay, composite: true,
     keywords: [开发, 编码, 实现, 写代码, 落地, 编程]}
  - {name: product,   prefix: "[产品]",  handoff: relay, composite: true,
     keywords: [产品, 需求, 规划, 排期]}
  - {name: reviewer,  prefix: "[评审]",  handoff: relay, composite: true,
     keywords: [评审, 审查, 复核, 走查, 检视]}
entry_ref: "https://cnb.cool/dongdongxiaozu/dongjiagoushi"
capability_tags: [架构设计, 编码实现, 协作编排, 接力交接, 经验记忆]
register_version: "1.1"
```

## 验收标准（单位接入后须达标）
- 路由命中：行业别名能正确路由到单位（≥90%）。
- 前缀稳定：单会话内岗位前缀零突变。
- 交接成功：跨行业/跨岗位交接卡能闭合。
- 复合可用：可装配 ≥2 岗位同会话运行。
- 数据驱动：新增行业只需注册数据即可被路由（无需改代码）。

## M11 岗位画像（可选但推荐）

注册表的 `roles` 只描述"路由信号"（名/前缀/关键词）。要把岗位真的跑起来，还需在
`data/role-profiles/<unit_id>.yaml` 为每个岗位补六维画像：

```yaml
roles:
  - role: architect
    analysis:     {mission, deliverables, inputs, outputs, kpis}
    persona:      {seniority, mindset, tone, decision_rights, constraints}
    plugin:       {bundle, tools, mcp_categories, artifacts, install_hint}
    workflow:     {default_flow, templates: [{template, id, name, override: {steps}}]}
    stakeholders: {upstream, downstream, beneficiaries, blockers, incentives, risk_notes}
    capability:   {core, tools, knowledge, soft, scoring: {domain, tooling, judging, execution, comms}}
```

缺项不阻塞接入：渲染器会照常生成岗位卡，并在就绪度里**如实扣分 + 登记缺口**。
补完执行 `python3 scripts/gen_rolecards.py --unit <unit_id>` 重渲，`role list --unit <unit_id>` 看就绪度。
契约与评分口径见 `data/rolecard-schema.yaml`，设计见 `docs/architecture/M11-岗位画像层.md`。
