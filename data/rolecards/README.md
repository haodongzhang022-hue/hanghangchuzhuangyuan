# 岗位卡（data/rolecards）· 机器渲染产物

> ⚠️ 本目录是 `scripts/gen_rolecards.py` 的产物，**请勿手改**。改了下次渲染就被覆盖。

它把四份数据合成一份可执行的岗位卡：

| 输入 | 提供什么 |
|------|----------|
| `data/role-profiles/<unit>.yaml` | 六维评估（人写） |
| `data/industry-register.yaml` 等 | 岗位事实：名/前缀/关键词/行业 |
| `data/workflow-templates/*.yaml` | 通用工序（岗位只写覆盖） |
| `vendor/upstream/knowledge-work-plugins`（可选） | 技能包清单（`plugin_artifacts`） |

为什么提交入库而不是每次现算：能被 review、能 diff、能被 n8n / 纯代码 / 别的 Agent 直接读，
不必装 Python。

```bash
python3 scripts/gen_rolecards.py --from-kwp vendor/upstream/knowledge-work-plugins
python3 scripts/gen_rolecards.py --check   # CI：产物是否与数据一致
```
