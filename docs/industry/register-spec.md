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
entry_ref: 单位仓库地址
capability_tags: [跨界检索关键词]
register_version: 版本号
```

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
  - {name: secretary, prefix: "[秘书]",  handoff: relay, composite: true}
  - {name: architect, prefix: "[架构]",  handoff: relay, composite: true}
  - {name: developer, prefix: "[开发]",  handoff: relay, composite: true}
  - {name: product,   prefix: "[产品]",  handoff: relay, composite: true}
  - {name: reviewer,  prefix: "[评审]",  handoff: relay, composite: true}
entry_ref: "https://cnb.cool/dongdongxiaozu/dongjiagoushi"
capability_tags: [架构设计, 编码实现, 协作编排, 接力交接, 经验记忆]
register_version: "1.0"
```

## 验收标准（单位接入后须达标）
- 路由命中：行业别名能正确路由到单位（≥90%）。
- 前缀稳定：单会话内岗位前缀零突变。
- 交接成功：跨行业/跨岗位交接卡能闭合。
- 复合可用：可装配 ≥2 岗位同会话运行。
