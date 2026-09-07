# 功能特性交付索引（行业扩展第四期：人力资源/行政办公/视觉设计 · coverage 进度校准）

> 版本：行业横向扩展 v4 | 2026-09-08 | 同步人：CodeBuddy
> 场景：按 coverage 目标全集缺口优先级推进，新增人力资源/行政办公/视觉设计 3 个高优先级行业单元，
> 填补招聘/离职/薪酬绩效、公文/档案/会务、海报/UI/插画/品牌视觉等高频诉求盲区。
> 前置：PR #20 已建立 coverage 覆盖进度机制（11 已覆盖 + 21 待补缺口）；本期将高优先级缺口 3/21 落地为已覆盖。
> 关联：ISSUE #19（整体目标 vs 当前进度的系统化展现）

---

## 1. 总览

围绕「按缺口优先级推进行业覆盖」主线，把 `coverage-target.yaml` 中 **priority=高** 的三个缺口行业补齐为正式单元，
行业覆盖从 11 提升至 **14/32**，岗位覆盖从 38 提升至 **50**。纯数据驱动 + coverage 目标全集同步校准，无核心代码逻辑改动。

| 功能编号 | 功能名称 | 状态 | 涉及文件 |
|---------|---------|------|---------|
| C-01 | 新增 hr-services 人力资源单元（4岗） | ✅ 已完成 | data/unit-index.yaml |
| C-02 | 新增 admin-office 行政办公单元（4岗） | ✅ 已完成 | data/unit-index.yaml |
| C-03 | 新增 design-visual 视觉设计单元（4岗） | ✅ 已完成 | data/unit-index.yaml |
| C-04 | coverage-target.yaml 校准（pending→registered，v0.2） | ✅ 已完成 | data/coverage-target.yaml |
| C-05 | prefix-archive 扩展至 14 单元 | ✅ 已完成 | data/prefix-archive.json |
| C-06 | 新增行业路由回归 + coverage 进度断言测试 | ✅ 已完成 | tests/test_industry_expansion_v4.py |
| C-07 | README / docs/industry/units 同步至 14 单元 | ✅ 已完成 | README.md / docs/industry/units/* |

---

## 2. 新增行业详情

### C-01 hr-services 人力资源（高优先级缺口）

覆盖场景：招聘/猎头 / 薪酬绩效 / 员工关系(入离职/社保/劳动纠纷) / HR 咨询(组织/人才/编制)

| 岗位 | 前缀 | 职责 |
|------|------|------|
| recruiter | [招聘] | 招聘 人才寻访 猎头 简历筛选 面试邀约 |
| comp_benefits | [薪酬绩效] | 薪酬核算 绩效方案 调薪 奖金 |
| employee_relations | [员工关系] | 入离职 劳动合同 社保 劳动纠纷 员工关怀 |
| hr_advisor | [HR顾问] | 人力规划 组织发展 定岗定编 制度设计 |

### C-02 admin-office 行政办公（高优先级缺口）

覆盖场景：行政采购/后勤 / 前台接待 / 公文档案 / 会务差旅

| 岗位 | 前缀 | 职责 |
|------|------|------|
| admin_specialist | [行政专员] | 行政事务 办公采购 后勤 环境 |
| receptionist | [前台] | 前台 访客接待 来电 |
| document_archivist | [档案文书] | 公文写作 档案管理 资料归档 |
| meeting_coordinator | [会务] | 会议组织 会务 差旅 活动 |

### C-03 design-visual 视觉设计（高优先级缺口）

覆盖场景：平面/海报 / UI/交互 / 插画 / 品牌VI与电商视觉

| 岗位 | 前缀 | 职责 |
|------|------|------|
| graphic_designer | [平面设计] | 海报 画册 宣传物料 版式 |
| ui_designer | [UI设计] | 界面设计 网页/App UI 交互原型 |
| illustrator | [插画] | 插画 手绘 卡通形象 表情包 |
| brand_designer | [品牌视觉] | 品牌 VI logo 包装 电商详情页 |

---

## 3. 覆盖进度（coverage 输出）

| 指标 | 覆盖 | 总量 | 覆盖率 |
|------|------|------|--------|
| 行业 | 14 | 32 | 43.8% |
| 岗位 | 50 | 140 | 35.7% |

待补缺口从 21 降至 **18**（已补 3 个高优先级：人力资源/行政办公/视觉设计）。

---

## 4. 验证

- `tests/test_industry_expansion_v4.py` 全绿（注册/路由/回归护栏/coverage 进度/prefix-archive）
- CLI `route` 对新三行业各岗位冒烟通过
- CLI `coverage` / `coverage --gaps` 正常反映 14/32 与剩余缺口
