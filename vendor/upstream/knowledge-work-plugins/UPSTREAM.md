# 上游快照信息

- 上游仓库：https://github.com/anthropics/knowledge-work-plugins
- 快照 commit：`2574e29377c7173d0cecffef29a6ecbd7f8ccb5d`
- 快照时间：见本仓库引入该目录的提交
- 许可：Apache-2.0（原样保留 `LICENSE`）
- 处理：仅删除 `.git`，文件内容未做任何修改

## 我方如何消费这份快照

| 消费点 | 说明 |
|--------|------|
| `scripts/gen_rolecards.py --from-kwp <dir>` | 解析各插件 `skills/*/SKILL.md` 的 frontmatter，生成 `data/rolecards/*.yaml` 的 `plugin_artifacts` 与 `workflows[].playbook` 段落 |
| `data/role-profiles/*.yaml` | 我方自有的岗位画像人工基线（分析/画像/利益链条/核心能力评分），与上游解耦 |

上游只提供「岗位 → 技能包 → 工作流命令」的**包装形态**参考；
岗位的**评估表、利益链条、能力评分、路由激活条件**由我方 M11 数据层定义。
