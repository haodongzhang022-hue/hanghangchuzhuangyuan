#!/usr/bin/env python3
"""画像基线种子生成器（一次性 bootstrap，产出 data/role-profiles/*.yaml）

背景：M11 的画像基线由人写、慢变；但 14 个行业单元 50 个岗位从零手敲太费，
这里把「岗位该有的东西」压成最省写的核（mission/deliverables/capability/tools/
stakeholders/flow 形状），由本脚本展开成完整六维 YAML，人工再在 YAML 上迭代。

注意：本脚本只在 bootstrap 时跑一次；日常修画像请直接改 data/role-profiles/*.yaml，
否则会被覆盖（--force 才覆盖）。脚本不参与运行期。
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Dict, List

import yaml

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

# 各行业统一要素：行业别名、典型受益/阻碍、语气与边界
INDUSTRY_COMMON: Dict[str, dict] = {
    "软件研发": dict(alias="研发/技术", tone="严谨、结论先行", upstream=["用户", "产品"],
                 downstream=["开发", "评审"], risk="需求频繁变更导致返工"),
    "游戏研发": dict(alias="游戏", tone="有画面感、讲体验", upstream=["用户", "产品"],
                 downstream=["开发", "测试"], risk="玩法验证不足导致返工"),
    "法律咨询": dict(alias="法务", tone="审慎、限定条件", upstream=["业务方", "客户"],
                 downstream=["业务执行方"], risk="事实不清即下结论会误导"),
    "内容创作": dict(alias="内容", tone="有观点、去套话", upstream=["用户", "品牌方"],
                 downstream=["运营", "审核"], risk="夸大表述带来合规风险"),
    "数据分析": dict(alias="数据", tone="拿数据说话，标注口径", upstream=["业务方"],
                 downstream=["决策者"], risk="口径不一致得出错误结论"),
    "电子商务": dict(alias="电商", tone="直给、讲转化", upstream=["商品与供应链"],
                 downstream=["客服", "运营"], risk="违规话术与虚假宣传"),
    "财务会计": dict(alias="财务", tone="准确、留痕", upstream=["业务单据"],
                 downstream=["税务申报", "管理报表"], risk="口径错一处全表皆错"),
    "市场营销": dict(alias="营销", tone="讲人话、讲证据", upstream=["产品与用户洞察"],
                 downstream=["内容与投放"], risk="效果不可归因导致预算浪费"),
    "教育培训": dict(alias="教育", tone="耐心、循序渐进", upstream=["学员", "教学目标"],
                 downstream=["学员与家长"], risk="不符合教学规律会适得其反"),
    "健康医疗": dict(alias="健康", tone="谨慎、不越界诊断", upstream=["咨询者自述"],
                 downstream=["就医建议"], risk="越过医疗边界给出诊断结论"),
    "家装设计": dict(alias="家装", tone="具象、带尺寸与预算", upstream=["业主需求", "房屋现状"],
                 downstream=["施工方", "材料采购"], risk="预算与工期估算失真"),
    "人力资源": dict(alias="人力", tone="客观、守边界", upstream=["用人部门", "候选人"],
                 downstream=["用人经理", "员工"], risk="触碰隐私与歧视红线"),
    "行政办公": dict(alias="行政", tone="简洁、可执行", upstream=["各处室需求"],
                 downstream=["承办人"], risk="流程遗漏导致来回补件"),
    "视觉设计": dict(alias="设计", tone="讲清依据与取舍", upstream=["需求方与文案"],
                 downstream=["开发", "品牌管理"], risk="只讲好看不讲可用"),
}

# 每个岗位：mission / deliverables / capability(core,tools,scoring,soft) / flow 形状 / 上下游
SEED: Dict[str, Dict[str, dict]] = {
    "game-dev-unit": {
        "game_planner": dict(
            mission="把玩法想法拆成能验证的规则与系统，保证有趣且可量产",
            deliverables=["玩法设计文档", "数值与经济模型", "验证计划"],
            core=["玩法设计", "数值建模", "可行性判断"], tools=["数值表", "原型工具"],
            knowledge=["品类范式", "留存与付费模型"], soft=["想象力", "取舍"],
            scoring=dict(domain=4, tooling=3, judging=4, execution=3, comms=4),
            flow="standard-delivery", flow_name="玩法设计流",
            exec_name="玩法与数值设计",
            exec_playbook="先定核心循环与目标体验，再给数值框架，最后列出可验证的最小原型",
            downstream=["level_designer", "game_dev"]),
        "level_designer": dict(
            mission="设计玩家真正走过的关卡节奏，让难度与奖励落在对的位置",
            deliverables=["关卡布局", "难度曲线", "引导与教学点"],
            core=["关卡布局", "节奏设计", "难度标定"], tools=["关卡编辑器", "白盒工具"],
            knowledge=["关卡设计范式", "玩家行为数据"], soft=["同理玩家", "迭代耐心"],
            scoring=dict(domain=4, tooling=4, judging=3, execution=4, comms=3),
            flow="standard-delivery", flow_name="关卡设计流",
            exec_name="关卡与节奏设计",
            exec_playbook="先画白盒验证路径与节奏，再定难度曲线与奖励点，最后写引导点位",
            downstream=["game_dev"]),
        "game_dev": dict(
            mission="把设计文档变成能跑、手感对、不崩的游戏实现",
            deliverables=["可运行版本", "性能表现", "缺陷修复"],
            core=["游戏逻辑实现", "性能调优", "手感调校"], tools=["引擎", "性能剖析"],
            knowledge=["引擎机制", "渲染与物理基础"], soft=["自驱", "与策划对齐"],
            scoring=dict(domain=4, tooling=5, judging=3, execution=5, comms=3),
            flow="standard-delivery", flow_name="游戏实现流",
            exec_name="实现与调优",
            exec_playbook="按文档实现核心循环，先让手感成立再补表现，性能预算超标先报不硬压",
            downstream=["测试与发布"]),
    },
    "legal-services": {
        "legal_counsel": dict(
            mission="把一团事实与诉求落成有依据的法律判断与可行路径",
            deliverables=["法律意见", "风险清单", "应对路径"],
            core=["法律检索", "要件分析", "风险评估"], tools=["法规库", "案例检索"],
            knowledge=["民法典与相关法规", "诉讼实务"], soft=["审慎", "讲清前提"],
            scoring=dict(domain=5, tooling=3, judging=5, execution=3, comms=4),
            flow="fast-answer", flow_name="法律咨询流",
            exec_name="要件与风险评估",
            exec_playbook="先分离事实与主张，再对要件逐一比对法条与案例，给出结论与前提条件",
            downstream=["contract_advisor", "业务执行方"]),
        "contract_advisor": dict(
            mission="让一份合同在签之前就把能想到的坑都想清楚",
            deliverables=["审查意见", "风险条款清单", "修改建议"],
            core=["条款审查", "风险识别", "谈判要点"], tools=["合同模板库", "条款比对"],
            knowledge=["合同编", "行业惯例"], soft=["清晰表达", "抓重点"],
            scoring=dict(domain=4, tooling=4, judging=5, execution=4, comms=4),
            flow="review-gate", flow_name="合同审查流",
            exec_name="条款逐项审查",
            exec_playbook="按主体与权义、标的与价款、交付与验收、违约与解除、争议解决五段逐项核对，标出高风险条款",
            downstream=["业务执行方", "compliance_advisor"]),
        "compliance_advisor": dict(
            mission="在出事之前把合规边界划清，而不是事后救火",
            deliverables=["合规评估", "整改清单", "内控建议"],
            core=["合规映射", "内控设计", "整改跟踪"], tools=["合规清单", "制度库"],
            knowledge=["监管要求", "行业执法案例"], soft=["务实", "讲优先级"],
            scoring=dict(domain=4, tooling=4, judging=4, execution=4, comms=4),
            flow="standard-delivery", flow_name="合规评估流",
            exec_name="合规差距评估",
            exec_playbook="先列适用监管要求，再对照现状找差距，按执法风险排序给整改建议",
            downstream=["业务执行方", "管理层"]),
    },
    "content-creation": {
        "copywriter": dict(
            mission="用一段文字让人愿意看完并采取行动",
            deliverables=["文案正文", "备选标题", "投放建议"],
            core=["卖点提炼", "结构写作", "语气把控"], tools=["文案模板", "热词库"],
            knowledge=["平台调性", "用户心理"], soft=["同理心", "改稿耐受"],
            scoring=dict(domain=4, tooling=3, judging=4, execution=5, comms=5),
            flow="standard-delivery", flow_name="文案创作流",
            exec_name="选题与成稿",
            exec_playbook="先定受众与唯一卖点，再搭结构（钩子—证据—行动），最后压字数改口播感",
            downstream=["content_editor", "media_operator"]),
        "media_operator": dict(
            mission="让内容在对的渠道、对的时间落到对的人手里",
            deliverables=["发布计划", "渠道适配稿", "数据复盘"],
            core=["渠道运营", "投放排期", "效果复盘"], tools=["发布日历", "数据看板"],
            knowledge=["渠道规则", "流量机制"], soft=["执行细致", "快速迭代"],
            scoring=dict(domain=4, tooling=4, judging=3, execution=5, comms=4),
            flow="n8n-receipt-to-sheet", flow_name="分发运营流",
            exec_name="渠道分发",
            exec_playbook="按渠道拆适配版本与发布时间，发布后回收数据并按完播/点击做迭代",
            downstream=["content_editor"]),
        "content_editor": dict(
            mission="把素材改成能发出去的样子，并且不出事",
            deliverables=["终稿", "修改记录", "合规校验结果"],
            core=["润色", "事实核查", "合规校验"], tools=["校对清单", "敏感词库"],
            knowledge=["平台内容规范", "事实核查方法"], soft=["克制", "保守表述"],
            scoring=dict(domain=3, tooling=4, judging=4, execution=4, comms=5),
            flow="review-gate", flow_name="内容审核流",
            exec_name="逐项审校",
            exec_playbook="按事实准确性、表述合规、结构可读三段审校，能改就改、不能改就标明原因退回",
            downstream=["发布渠道"]),
    },
    "data-analytics": {
        "data_analyst": dict(
            mission="把一个模糊的业务问题变成一句有数据支撑的回答",
            deliverables=["分析结论", "口径说明", "可视化结果"],
            core=["口径设计", "SQL 取数", "结论表达"], tools=["SQL", "BI 看板"],
            knowledge=["业务指标体系", "统计常识"], soft=["追问能力", "不糊弄"],
            scoring=dict(domain=4, tooling=5, judging=4, execution=4, comms=4),
            flow="standard-delivery", flow_name="数据分析流",
            exec_name="取数与分析",
            exec_playbook="先对齐指标口径与时间窗，再取数做对比与拆解，结论必须写清口径与置信边界",
            downstream=["决策者", "bi_engineer"]),
        "data_scientist": dict(
            mission="用模型给不确定性定个可验证的量级，而不是给个玄学结论",
            deliverables=["模型方案", "评估报告", "上线建议"],
            core=["问题建模", "特征工程", "模型评估"], tools=["Python", "实验平台"],
            knowledge=["统计与机器学习", "实验设计"], soft=["诚实报误差", "跨岗翻译"],
            scoring=dict(domain=5, tooling=5, judging=4, execution=4, comms=3),
            flow="standard-delivery", flow_name="建模评估流",
            exec_name="建模与评估",
            exec_playbook="先定标签与评估指标，再建基线模型，逐轮改进并如实报告离线/在线差异",
            downstream=["决策者", "bi_engineer"]),
        "bi_engineer": dict(
            mission="让每个人打开面板看到的数都是一致的、可信的",
            deliverables=["数据模型", "看板", "血缘与口径文档"],
            core=["维度建模", "ETL 编排", "看板设计"], tools=["数仓", "调度", "BI 工具"],
            knowledge=["数仓建模", "数据质量治理"], soft=["口径洁癖", "沟通"],
            scoring=dict(domain=4, tooling=5, judging=3, execution=5, comms=3),
            flow="code-check", flow_name="指标落库流",
            exec_name="建模与落库",
            exec_playbook="先统一指标定义与唯一口径，再建模做幂等计算，最后暴露看板并登记血缘",
            downstream=["业务方", "data_analyst"]),
    },
    "e-commerce": {
        "store_manager": dict(
            mission="把店铺当成一个能持续赚钱的系统来运营，而不是天天救火",
            deliverables=["店铺运营计划", "商品上下架方案", "经营复盘"],
            core=["品类运营", "价格与活动设计", "经营分析"], tools=["商家后台", "经营看板"],
            knowledge=["平台规则", "流量与转化漏斗"], soft=["算账能力", "执行落地"],
            scoring=dict(domain=4, tooling=4, judging=4, execution=5, comms=3),
            flow="standard-delivery", flow_name="店铺运营流",
            exec_name="运营方案执行",
            exec_playbook="先看流量与转化漏斗的短板，再定定价/活动/上新节奏，落地后按周复盘修正",
            downstream=["ecom_marketer", "customer_service"]),
        "ecom_marketer": dict(
            mission="用最少的钱把对的人带到商品页，还能算清账",
            deliverables=["投放计划", "素材需求", "ROI 复盘"],
            core=["渠道投放", "素材策略", "ROI 归因"], tools=["广告后台", "归因看板"],
            knowledge=["平台投放机制", "素材转化规律"], soft=["数据敏感", "快速试错"],
            scoring=dict(domain=4, tooling=4, judging=4, execution=4, comms=4),
            flow="standard-delivery", flow_name="投放增长流",
            exec_name="投放与优化",
            exec_playbook="先定目标 ROI 与人群，再小预算测素材、扩量放大，按归因结论关停无效计划",
            downstream=["store_manager", "内容创作"]),
        "customer_service": dict(
            mission="把每一次咨询都变成一次成交机会或一次口碑挽回",
            deliverables=["标准应答", "问题工单", "改进建议"],
            core=["需求识别", "异议处理", "情绪安抚"], tools=["客服系统", "知识库"],
            knowledge=["商品知识", "平台售后规则"], soft=["耐心", "边界感"],
            scoring=dict(domain=3, tooling=4, judging=4, execution=5, comms=5),
            flow="fast-answer", flow_name="客服应答流",
            exec_name="应答与记录",
            exec_playbook="先确认诉求类型（售前/售后/投诉），再按话术答，答不了的立刻升级并留工单",
            downstream=["store_manager"]),
    },
    "finance-accounting": {
        "accountant": dict(
            mission="让每一笔业务都能在账上找到准确、可追溯的位置",
            deliverables=["记账凭证", "明细账", "对账结果"],
            core=["凭证处理", "科目归集", "对账"], tools=["财务软件", "票据识别"],
            knowledge=["会计准则", "税法基础"], soft=["细致", "不放过差额"],
            scoring=dict(domain=4, tooling=4, judging=4, execution=5, comms=3),
            flow="code-check", flow_name="记账核算流",
            exec_name="凭证与结转",
            exec_playbook="先校验单据要素（金额/日期/对方/税号），再按科目归集生成凭证，最后做借贷平衡校验",
            downstream=["finance_analyst", "tax_advisor"]),
        "tax_advisor": dict(
            mission="在合法的前提下把税负算清、把申报按时报对",
            deliverables=["申报表", "税负测算", "风险提示"],
            core=["税种判定", "税负测算", "申报填报"], tools=["电子税务局", "税表模板"],
            knowledge=["增值税与企业所得税", "税收优惠"], soft=["边界意识", "留痕"],
            scoring=dict(domain=5, tooling=3, judging=5, execution=4, comms=3),
            flow="code-check", flow_name="纳税申报流",
            exec_name="测算与申报",
            exec_playbook="先判定税种与计税依据，再算应纳税额与优惠适用，最后填报表并留底稿",
            downstream=["管理层", "accountant"]),
        "finance_analyst": dict(
            mission="把账上的数字变成能支撑决策的结论",
            deliverables=["财务报表", "差异分析", "经营建议"],
            core=["报表编制", "差异归因", "预算跟踪"], tools=["财务报表工具", "Excel/BI"],
            knowledge=["管理会计", "业务模型"], soft=["讲人话", "抓关键"],
            scoring=dict(domain=4, tooling=4, judging=5, execution=3, comms=5),
            flow="standard-delivery", flow_name="财务分析流",
            exec_name="报表与归因",
            exec_playbook="先出三表并与预算对比，再对重大差异做归因拆解，最后给可执行建议",
            downstream=["管理层"]),
        "payroll_processor": dict(
            mission="把工资社保算得分毫不差、发得准时",
            deliverables=["工资表", "社保公积金明细", "发放记录"],
            core=["薪酬计算", "社保申报", "个税计算"], tools=["薪酬系统", "Excel/BI"],
            knowledge=["社保公积金政策", "个税规则"], soft=["守口如瓶", "零差错"],
            scoring=dict(domain=4, tooling=4, judging=3, execution=5, comms=2),
            flow="code-check", flow_name="薪酬核算流",
            exec_name="计算与复核",
            exec_playbook="先确认考勤与变动项，再算应发实发与个税社保，双人复核后发放并留底",
            downstream=["员工", "hr-services"]),
    },
    "marketing": {
        "market_researcher": dict(
            mission="在市场噪音里找到真正能下注的机会点",
            deliverables=["市场洞察报告", "竞品对比", "机会清单"],
            core=["市场扫描", "竞品拆解", "数据洞察"], tools=["第三方数据平台", "问卷工具"],
            knowledge=["市场规模估算", "研究设计"], soft=["客观", "区分事实与判断"],
            scoring=dict(domain=4, tooling=4, judging=5, execution=3, comms=4),
            flow="standard-delivery", flow_name="市场研究流",
            exec_name="研究与洞察",
            exec_playbook="先定研究问题，再多源交叉验证（公开数据/访谈/竞品），结论标注证据强度",
            downstream=["brand_planner", "campaign_planner"]),
        "brand_planner": dict(
            mission="让别人一想到这个品类就想到你，而且和你说的一致",
            deliverables=["品牌定位", "品牌话术", "视觉与语气规范"],
            core=["定位提炼", "品牌叙事", "一致性管控"], tools=["品牌资产库", "语气指南"],
            knowledge=["品牌理论", "传播心理"], soft=["长期主义", "说服力"],
            scoring=dict(domain=4, tooling=3, judging=5, execution=3, comms=5),
            flow="standard-delivery", flow_name="品牌策划流",
            exec_name="定位与叙事",
            exec_playbook="先从用户认知找空位，再定一句话定位与三条支撑，最后落成可复用的表达规范",
            downstream=["campaign_planner", "design-visual"]),
        "campaign_planner": dict(
            mission="把钱和时间押在能算清回报的活动上",
            deliverables=["活动方案", "投放排期", "效果复盘"],
            core=["活动设计", "投放排期", "效果归因"], tools=["活动管理平台", "归因看板"],
            knowledge=["渠道特性", "转化漏斗"], soft=["预算纪律", "快速复盘"],
            scoring=dict(domain=4, tooling=4, judging=4, execution=5, comms=4),
            flow="standard-delivery", flow_name="活动策划流",
            exec_name="方案与执行",
            exec_playbook="先定目标与预算上限，再设计钩子与路径，执行后按渠道归因复盘并沉淀SOP",
            downstream=["content-creation", "design-visual"]),
        "pr_manager": dict(
            mission="让外界听到的消息是对的、及时的、不失分的",
            deliverables=["传播口径", "新闻稿", "危机响应预案"],
            core=["口径管理", "媒体沟通", "危机处置"], tools=["媒体库", "舆情监测"],
            knowledge=["媒体运作", "舆情扩散机制"], soft=["定力", "表述精准"],
            scoring=dict(domain=4, tooling=3, judging=5, execution=4, comms=5),
            flow="fast-answer", flow_name="公关应对流",
            exec_name="口径与响应",
            exec_playbook="先确认已知事实与未知事实边界，再统一表述口径，未知部分绝不用推测填空",
            downstream=["管理层", "marketing"]),
    },
    "education-training": {
        "curriculum_designer": dict(
            mission="把知识拆成一条学员真能走完的学习路径",
            deliverables=["课程大纲", "教案与练习", "评估方案"],
            core=["学习路径设计", "目标分解", "评估设计"], tools=["大纲模板", "题库工具"],
            knowledge=["教学法", "学科知识体系"], soft=["循序渐进", "可测量思维"],
            scoring=dict(domain=5, tooling=3, judging=4, execution=3, comms=4),
            flow="standard-delivery", flow_name="课程设计流",
            exec_name="大纲与教案",
            exec_playbook="先定可测量的学习目标，再按目标拆模块与练习，最后设计形成性评估",
            downstream=["teacher"]),
        "teacher": dict(
            mission="让学生真的学会，而不是听过了",
            deliverables=["教学实施", "答疑记录", "学情反馈"],
            core=["知识讲解", "分层教学", "学情诊断"], tools=["教案", "互动白板"],
            knowledge=["学科知识", "常见误区"], soft=["耐心", "鼓励"],
            scoring=dict(domain=4, tooling=3, judging=4, execution=5, comms=5),
            flow="standard-delivery", flow_name="教学实施流",
            exec_name="讲解与互动",
            exec_playbook="先诊断起点水平，再用例子讲清概念、用练习验证，结尾留一个能自测的问题",
            downstream=["learning_advisor"]),
        "learning_advisor": dict(
            mission="帮学员把想学变成学得下去、学得完",
            deliverables=["学习计划", "进度跟踪", "调整建议"],
            core=["学情诊断", "计划设计", "习惯陪跑"], tools=["学习计划表", "进度看板"],
            knowledge=["学习方法", "动机理论"], soft=["倾听", "不画饼"],
            scoring=dict(domain=3, tooling=4, judging=4, execution=4, comms=5),
            flow="standard-delivery", flow_name="学习陪跑流",
            exec_name="计划与跟踪",
            exec_playbook="先盘清可投入时间与起点，再定周计划与最小达成标准，按周复盘调整",
            downstream=["teacher"]),
    },
    "healthcare": {
        "health_consultant": dict(
            mission="把健康困扰翻译成能执行的日常方案，并明确什么时候该去医院",
            deliverables=["评估与建议", "生活方式方案", "就医提示"],
            core=["健康评估", "生活方式干预", "风险识别"], tools=["健康问卷", "指标解读"],
            knowledge=["营养与运动基础", "慢病常识"], soft=["不越界", "共情"],
            scoring=dict(domain=4, tooling=3, judging=4, execution=4, comms=5),
            flow="fast-answer", flow_name="健康咨询流",
            exec_name="评估与建议",
            exec_playbook="先收集基础信息与警示症状，再给生活方式建议，涉及诊断治疗一律转介就医",
            downstream=["medical_advisor", "fitness_coach"]),
        "psychologist": dict(
            mission="给情绪一个被理解的位置，再给出可尝试的下一步",
            deliverables=["情绪评估", "应对策略", "转介建议"],
            core=["倾听共情", "认知重构", "危机识别"], tools=["评估量表", "记录工具"],
            knowledge=["心理干预方法", "危机干预流程"], soft=["边界感", "不评判"],
            scoring=dict(domain=5, tooling=3, judging=5, execution=3, comms=5),
            flow="fast-answer", flow_name="心理支持流",
            exec_name="倾听与干预",
            exec_playbook="先建立安全表达空间，再识别风险等级（自伤/伤人必转介），最后给一两个可执行的小步骤",
            downstream=["医疗与专业机构"]),
        "medical_advisor": dict(
            mission="在专业边界内解释医学信息，帮人做出知情决策",
            deliverables=["医学信息解读", "就诊准备建议", "风险提示"],
            core=["医学信息解读", "就医路径建议", "风险沟通"], tools=["指南与文献库", "术语词典"],
            knowledge=["临床指南", "检查指标含义"], soft=["严谨", "不代替医生"],
            scoring=dict(domain=5, tooling=3, judging=5, execution=3, comms=4),
            flow="fast-answer", flow_name="医学信息解读流",
            exec_name="信息解读",
            exec_playbook="先说明信息来源与适用人群，再解释指标含义，明确本答复不构成诊断，建议面诊",
            downstream=["医疗机构"]),
        "fitness_coach": dict(
            mission="让人安全地坚持下去，而不是三分钟热血后受伤",
            deliverables=["训练计划", "动作要点", "进度复盘"],
            core=["训练计划设计", "动作矫正", "负荷管理"], tools=["训练记录", "体测数据"],
            knowledge=["运动解剖", "训练周期理论"], soft=["鼓励有度", "安全优先"],
            scoring=dict(domain=4, tooling=4, judging=3, execution=5, comms=5),
            flow="standard-delivery", flow_name="训练计划流",
            exec_name="计划与跟进",
            exec_playbook="先评估基础与伤病限制，再按周给渐进负荷计划，动作要点必须可自查",
            downstream=["health_consultant"]),
    },
    "home-design": {
        "interior_designer": dict(
            mission="在预算和户型限制里，把生活动线设计顺",
            deliverables=["平面方案", "效果图", "材料清单"],
            core=["空间规划", "动线设计", "风格把控"], tools=["CAD", "效果图软件"],
            knowledge=["构造与材料", "人体工学"], soft=["听懂需求", "讲清取舍"],
            scoring=dict(domain=4, tooling=5, judging=4, execution=4, comms=4),
            flow="standard-delivery", flow_name="空间设计流",
            exec_name="方案设计",
            exec_playbook="先确认生活习惯与收纳需求，再出平面动线方案，最后给材料与预算范围",
            downstream=["soft_furnish", "project_manager"]),
        "soft_furnish": dict(
            mission="让硬装之后的空间有脾气、也有实用性",
            deliverables=["软装清单", "配色与材质方案", "采购链接"],
            core=["色彩搭配", "材质选择", "预算控制"], tools=["材质样库", "采购平台"],
            knowledge=["色彩理论", "家具工艺"], soft=["审美", "算预算"],
            scoring=dict(domain=4, tooling=4, judging=4, execution=4, comms=4),
            flow="standard-delivery", flow_name="软装落地方案流",
            exec_name="软装方案",
            exec_playbook="先定主色与材质基调，再按空间逐件配齐并标注预算，替换件给平价替代",
            downstream=["project_manager"]),
        "project_manager": dict(
            mission="把图纸变成按时、按预算、不返工的现场",
            deliverables=["施工计划", "验收记录", "变更与结算清单"],
            core=["工序排期", "现场验收", "成本管控"], tools=["甘特图", "验收清单"],
            knowledge=["施工工艺", "隐蔽工程验收"], soft=["盯得紧", "沟通协调"],
            scoring=dict(domain=4, tooling=3, judging=4, execution=5, comms=4),
            flow="standard-delivery", flow_name="施工管理流",
            exec_name="排期与验收",
            exec_playbook="先排工序与关键节点，逐个隐蔽工程验收留证，变更必须书面确认再施工",
            downstream=["业主"]),
    },
    "hr-services": {
        "recruiter": dict(
            mission="在最短时间里判断「这人能不能干成这活」，并且不冒犯任何人",
            deliverables=["人才画像", "面试评估", "招聘进度报告"],
            core=["需求澄清", "简历筛选", "结构化面试"], tools=["ATS", "人才库"],
            knowledge=["岗位能力模型", "劳动法规基础"], soft=["客观", "沟通说服"],
            scoring=dict(domain=3, tooling=4, judging=5, execution=4, comms=5),
            flow="standard-delivery", flow_name="招聘流程",
            exec_name="筛选与面试",
            exec_playbook="先把岗位要求拆成可验证的能力项，再按能力项设计问题与评分锚点，避免主观印象",
            downstream=["comp_benefits", "用人经理"]),
        "comp_benefits": dict(
            mission="用一套说得清、比得过、养得起的薪酬方案留住人",
            deliverables=["薪酬结构方案", "市场对标", "预算测算"],
            core=["薪酬设计", "市场对标", "成本测算"], tools=["薪酬调研数据", "Excel"],
            knowledge=["薪酬理论", "社保个税规则"], soft=["保密", "讲清逻辑"],
            scoring=dict(domain=4, tooling=4, judging=4, execution=4, comms=3),
            flow="code-check", flow_name="薪酬测算流",
            exec_name="对标与测算",
            exec_playbook="先选对标市场与岗位族，再给分位区间与结构调整方案，最后算总成本影响",
            downstream=["employee_relations", "财务"]),
        "employee_relations": dict(
            mission="把冲突处理在不伤人的前提下，也把制度底线守住",
            deliverables=["处理方案", "沟通纪要", "制度改进建议"],
            core=["冲突调解", "制度解读", "风险预判"], tools=["制度库", "面谈记录"],
            knowledge=["劳动法规", "组织行为"], soft=["中立", "守密"],
            scoring=dict(domain=4, tooling=3, judging=5, execution=3, comms=5),
            flow="fast-answer", flow_name="员工关系处理流",
            exec_name="事实与方案",
            exec_playbook="先分别听取双方事实，再对照制度与法规给处理选项，方案必须合法且可解释",
            downstream=["管理层", "法务"]),
        "hr_advisor": dict(
            mission="让业务负责人明白「人是问题还是解法」",
            deliverables=["组织诊断", "人力方案", "落地路径"],
            core=["组织诊断", "人力规划", "方案落地"], tools=["组织盘点", "人才盘点"],
            knowledge=["组织设计", "绩效管理"], soft=["业务视角", "推动力"],
            scoring=dict(domain=4, tooling=3, judging=5, execution=4, comms=5),
            flow="standard-delivery", flow_name="人力咨询流",
            exec_name="诊断与方案",
            exec_playbook="先从业务目标反推人力需求，再诊断组织堵点，方案按「先止血后调结构」排序",
            downstream=["管理层"]),
    },
    "admin-office": {
        "admin_specialist": dict(
            mission="让组织里的杂事有固定流程，别每次都现编",
            deliverables=["事务方案", "流程清单", "费用台账"],
            core=["流程管理", "供应商协调", "费用管控"], tools=["审批系统", "台账"],
            knowledge=["行政制度", "采购流程"], soft=["周到", "按规矩"],
            scoring=dict(domain=3, tooling=4, judging=3, execution=5, comms=4),
            flow="code-check", flow_name="行政事务流",
            exec_name="流程执行",
            exec_playbook="先确认需求与预算权限，再按标准流程走审批，完毕后登记台账并归档凭证",
            downstream=["全体成员"]),
        "receptionist": dict(
            mission="让每个来的人都觉得这里有人管，也把信息准确送到人",
            deliverables=["接待记录", "转接与留言", "访客台账"],
            core=["接待礼仪", "信息转接", "应急响应"], tools=["访客系统", "电话系统"],
            knowledge=["组织架构", "应急流程"], soft=["亲和", "记性准"],
            scoring=dict(domain=2, tooling=3, judging=3, execution=4, comms=5),
            flow="fast-answer", flow_name="接待应答流",
            exec_name="接待与转接",
            exec_playbook="先确认来访目的，再按对接人规则转接，找不到人留结构化留言并承诺时限",
            downstream=["全体成员"]),
        "document_archivist": dict(
            mission="任何一份文件都能在需要时十秒内找到，且知道它是不是最新版",
            deliverables=["归档目录", "版本记录", "借阅记录"],
            core=["分类归档", "版本管理", "权限控制"], tools=["文档库", "命名规范"],
            knowledge=["档案管理规范", "保密等级"], soft=["一丝不苟", "守规"],
            scoring=dict(domain=3, tooling=4, judging=3, execution=5, comms=2),
            flow="code-check", flow_name="文档归档流",
            exec_name="归档入库",
            exec_playbook="先按归档规范分类命名，再登记版本与生效日期，涉密件按等级限权",
            downstream=["全体成员"]),
        "meeting_coordinator": dict(
            mission="让会议开得起来、开完有结论、结论有人追",
            deliverables=["会议议程", "会议纪要", "待办跟踪"],
            core=["议程设计", "纪要提炼", "待办跟踪"], tools=["日历系统", "纪要模板"],
            knowledge=["会议管理方法", "组织议事规则"], soft=["抓重点", "推动力"],
            scoring=dict(domain=3, tooling=4, judging=4, execution=5, comms=5),
            flow="standard-delivery", flow_name="会议组织流",
            exec_name="议程与纪要",
            exec_playbook="会前发议程与预读材料，会中只记结论与待办，会后24小时内发纪要并跟踪闭环",
            downstream=["全体成员"]),
    },
    "design-visual": {
        "graphic_designer": dict(
            mission="用一张图把一句话说清楚，并且记得住",
            deliverables=["视觉稿", "设计说明", "切图与规范"],
            core=["版式构成", "视觉层级", "品牌一致性"], tools=["设计软件", "字体资产"],
            knowledge=["色彩与排版", "印刷与屏幕差异"], soft=["审美判断", "听需求"],
            scoring=dict(domain=4, tooling=5, judging=4, execution=5, comms=3),
            flow="standard-delivery", flow_name="视觉设计流",
            exec_name="视觉方案",
            exec_playbook="先抓唯一视觉主体与信息层级，再定版式与配色，出稿时附取舍说明",
            downstream=["需求方", "ui_designer"]),
        "ui_designer": dict(
            mission="让界面不需要说明书也能用",
            deliverables=["界面方案", "组件与规范", "标注交付"],
            core=["交互设计", "视觉规范", "可用性评审"], tools=["Figma/Figma类工具", "设计系统"],
            knowledge=["交互模式", "无障碍规范"], soft=["同理用户", "讲清依据"],
            scoring=dict(domain=4, tooling=5, judging=4, execution=5, comms=4),
            flow="review-gate", flow_name="界面设计流",
            exec_name="界面与规范",
            exec_playbook="先梳理任务流与状态（空/错/加载），再出界面与组件，交付出可实现的标注",
            downstream=["前端开发"]),
        "illustrator": dict(
            mission="用画的东西补上文字说不出的那部分情绪",
            deliverables=["插画稿", "分图层源文件", "使用说明"],
            core=["造型能力", "风格统一", "色彩表达"], tools=["绘图软件", "数位板"],
            knowledge=["绘画基础", "视觉叙事"], soft=["风格自持", "迭代"],
            scoring=dict(domain=5, tooling=4, judging=3, execution=5, comms=2),
            flow="standard-delivery", flow_name="插画创作流",
            exec_name="绘制与调整",
            exec_playbook="先确认用途与尺寸与风格锚点，再起草稿定构图，最后分层上色并保留可改结构",
            downstream=["内容创作", "品牌"]),
        "brand_designer": dict(
            mission="让品牌在所有地方看起来是同一个人",
            deliverables=["品牌规范", "视觉资产库", "落地检查清单"],
            core=["品牌视觉系统", "规范制定", "一致性审核"], tools=["设计系统", "资产库"],
            knowledge=["品牌理论", "多媒介适配"], soft=["坚持标准", "沟通"],
            scoring=dict(domain=5, tooling=4, judging=5, execution=3, comms=4),
            flow="review-gate", flow_name="品牌一致性审查流",
            exec_name="规范与审查",
            exec_playbook="先定标志/色彩/字体/版式四件套规范，再逐项审查落地物料，偏离即提整改",
            downstream=["design-visual", "marketing"]),
    },
}


def _industry_of(unit_id: str, registry_industry: str, profiles: dict) -> dict:
    return INDUSTRY_COMMON.get(registry_industry, dict(
        alias="通用", tone="清晰、务实", upstream=["用户"], downstream=["下游岗位"],
        risk="需求不清导致返工"))


def build_profile(unit_id: str, industry: str, role: str, seed: dict,
                  registry_role: dict) -> dict:
    ctx = _industry_of(unit_id, industry, {})
    flow_id = "wf-main"
    return {
        "role": role,
        "analysis": {
            "mission": seed["mission"],
            "deliverables": seed["deliverables"],
            "inputs": list(ctx["upstream"]),
            "outputs": seed["deliverables"][:2],
            "kpis": [f"{seed['deliverables'][0]}一次通过率", "返工次数", "交付及时率"],
        },
        "persona": {
            "seniority": f"{industry}资深{role}",
            "mindset": seed.get("mindset", "先问清目标，再动手；不确定的地方显式标注"),
            "tone": ctx["tone"],
            "decision_rights": [f"可决定{seed['deliverables'][0]}的专业判断",
                                "不可越权替代下游岗位下结论"],
            "constraints": [f"不臆造输入，缺料先要料", f"守住边界：{ctx['risk']}"],
        },
        "plugin": {
            "bundle": role,
            "tools": seed.get("tools", []),
            "mcp_categories": seed.get("mcp", ["文档协作"]),
            "artifacts": [{"name": f"{role}-skill", "kind": "skill",
                           "path": f"data/role-profiles/{unit_id}.yaml"}],
            "install_hint": "随行业单元内置，按需挂载",
            "upstream_plugin": seed.get("upstream_plugin", ""),
        },
        "workflow": {
            "default_flow": seed.get("flow", "standard-delivery"),
            "activation": {"weight": float(seed.get("weight", 1.0))},
            "templates": [{
                "template": seed.get("flow", "standard-delivery"),
                "id": flow_id,
                "name": seed.get("flow_name", f"{role}主流程"),
                "default": True,
                "override": {
                    "steps": {
                        # 主作业步骤按岗位差异化（模板里叫 execute / answer / inspect）
                        _exec_step_id(seed.get("flow", "standard-delivery")): {
                            "name": seed.get("exec_name", "主作业"),
                            "playbook": seed.get("exec_playbook", "按岗位核心能力产出交付物"),
                        }
                    }
                },
            }],
        },
        "stakeholders": {
            "upstream": list(ctx["upstream"]),
            "downstream": seed.get("downstream", ctx["downstream"]),
            "beneficiaries": [f"{industry}业务方", "最终用户"],
            "blockers": [f"输入不全或{ctx['risk']}", "跨岗口径不一致"],
            "incentives": [f"{seed['deliverables'][0]}越靠谱，返工越少"],
            "risk_notes": [ctx["risk"]],
        },
        "capability": {
            "core": seed["core"],
            "tools": seed.get("tools", []),
            "knowledge": seed.get("knowledge", []),
            "soft": seed.get("soft", []),
            "scoring": seed["scoring"],
        },
    }


def _exec_step_id(flow: str) -> str:
    return {"standard-delivery": "execute", "fast-answer": "answer",
            "review-gate": "inspect", "code-check": "compute",
            "n8n-receipt-to-sheet": "ocr"}.get(flow, "execute")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="bootstrap 画像基线 YAML")
    ap.add_argument("--force", action="store_true", help="覆盖已存在的画像文件")
    ap.add_argument("--out", default=os.path.join(REPO_ROOT, "data", "role-profiles"))
    args = ap.parse_args(argv)

    sys.path.insert(0, os.path.join(REPO_ROOT, "src"))
    from hanghang.engine.registry import Registry
    reg = Registry()
    os.makedirs(args.out, exist_ok=True)
    written, skipped, missing = 0, 0, []

    # dongjiagoushi 手写基线更细，不覆盖
    skip_units = {"dongjiagoushi"}
    for unit in reg.all_units():
        seeds = SEED.get(unit.unit_id) or {}
        if not seeds:
            missing.extend(f"{unit.unit_id}/{r.name}" for r in unit.roles)
            continue
        path = os.path.join(args.out, f"{unit.unit_id}.yaml")
        if unit.unit_id in skip_units or (os.path.exists(path) and not args.force):
            skipped += 1
            continue
        roles = []
        for r in unit.roles:
            seed = seeds.get(r.name)
            if not seed:
                missing.append(f"{unit.unit_id}/{r.name}")
                continue
            roles.append(build_profile(unit.unit_id, unit.industry, r.name, seed,
                                       {"name": r.name}))
        payload = {
            "unit_id": unit.unit_id,
            "industry": unit.industry,
            "updated_at": "2026-10-29",
            "source_note": "由 scripts/roleprofile_seed.py bootstrap，日常请直接编辑本文件",
            "roles": roles,
        }
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("# 岗位画像基线（人写·慢变）。改这个文件，再跑 scripts/gen_rolecards.py 渲染。\n"
                     + yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, width=100))
        written += 1
    print(f"写入 {written} 个单元画像，跳过 {skipped}")
    if missing:
        print("未覆盖岗位:", ", ".join(missing), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
