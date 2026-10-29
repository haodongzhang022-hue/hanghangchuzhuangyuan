# 岗位画像基线（data/role-profiles）

**人写、慢变**。这里放每个岗位的六维评估事实，是 M11 的唯一人工数据源。

- 一个行业单元一个文件：`<unit_id>.yaml`，与 `data/industry-register.yaml` 的 `unit_id` 对齐。
- 六维字段与就绪度口径见 `data/rolecard-schema.yaml`。
- 缺字段**不报错**：渲染时如实扣分并写进缺口清单（`role list` 可见）。
- 改完必须重渲岗位卡，否则 `gen_rolecards.py --check` 会在 CI 里报过期：

```bash
python3 scripts/gen_rolecards.py            # 重渲 data/rolecards/
python3 src/hanghang/cli/main.py role list  # 看就绪度与缺口
```

写画像的三条硬要求：

1. **使命要具体**：写"用一套能落地的结构方案把需求与实现的鸿沟填平"，不要写"负责架构设计"。
2. **边界要能约束行为**：`persona.constraints` 用来防越界（如"不越过需求方改范围""不臆造输入"）。
3. **阻碍要真实**：`stakeholders.blockers` 写实际会被什么卡住，否则利益链条这张表就只是摆设。
