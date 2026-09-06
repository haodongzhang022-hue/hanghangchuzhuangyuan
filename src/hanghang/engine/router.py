"""M1 行业识别·意图路由 + M4 会话编排判定 + M6 复合装配"""
from __future__ import annotations

from typing import Dict, List, Optional

from .models import IndustryUnit, RouteResult, Role
from .registry import Registry


class IntentRouter:
    """
    M1 自动识别路由：
    将用户意图文本识别为 (行业单元, 岗位列表)，支持多岗位复合意图。

    数据驱动设计：岗位关键词不再依赖全局硬编码词典，而是从各单元注册声明中
    动态读取每个岗位的触发关键词（role.keywords / role.description）。
    """

    # 默认岗位优先级（用于复合仲裁的依赖序）
    # 各单元也可通过复合 boundary 覆盖此顺序。
    DEFAULT_ROLE_PRIORITY: List[str] = [
        "secretary", "product", "architect", "developer", "reviewer",
        "game_planner", "level_designer", "game_dev",
    ]

    # 歧义判定阈值：top2 达到 top1 此比例即判为歧义（相对分差）
    AMBIGUITY_RATIO_THRESHOLD = 0.65

    # 软件产物名词（区分"纯业务域作业"与"构建软件"的关键信号）。
    # 仅使用"产物名词"而非共享的开发动作词（如"开发"同时被 软件研发 与 游戏研发
    # 注册，若用作改判信号会误伤"开发一款游戏"类诉求）。
    # 联合判定：当文本命中此类产物名词、且候选单元是仅凭"业务领域名词"命中的
    # 纯业务域单元时，说明用户是想"为某业务领域构建软件/系统/工具/代码/APP"，
    # 业务名词只是软件的被构建对象 → 应改判给软件研发单元。
    #
    # 评审补强（第 5 轮）：产物名词在真实业务域作业中同样高频出现（如"写一篇
    # APP推广文案""用数据分析工具出报表""审软件采购合同""做系统性经营分析"），
    # 仅凭"文本含产物名词"即改判会把大量正当业务作业静默卷进软件研发。
    # 因此改判须满足【产物名词是句子的软件构建目标】：
    #   产物名词之后不得再出现"业务交付物/专业作业"名词 —— 若其后仍紧跟
    # 业务交付名词，说明产物名词只是修饰语/手段，用户真实诉求是业务作业本身，
    # 应路由到对应业务域单元而非软件研发（见 DOMAIN_DELIVERABLE_TERMS）。
    SOFTWARE_BUILD_TERMS: tuple = (
        "软件", "系统", "工具", "代码", "应用", "程序",
        "平台", "app", "APP", "App", "网页应用",
        "网站", "网页", "官网", "小程序", "前端", "后端",
        "爬虫", "博客", "CRM", "ERP", "管理系统",
        "网站系统", "电商网站", "企业网站",
    )

    # 明确"构建/开发"动作词（评审第 6 轮 critical 修复）。
    # 改判必须同时满足【存在明确构建动词】，否则以下副词/非构建用法会被误吞：
    #   - "系统的学一下法律"/"我要系统的掌握法律知识"：这里的"系统"=系统地（副词），
    #     不是软件产物 → 不能改判软件研发；
    #   - "软件产品要怎么推广"：这是软件营销/内容诉求（推广），并非"要做一个软件"。
    # 故：仅当文本出现明确的软件"构建/开发"动作词、且该动作指向软件产物名词时，
    # 才判定为"为某业务领域构建软件"的开发诉求。
    SOFTWARE_BUILD_VERBS: tuple = (
        "开发", "研发", "构建", "搭建", "制作", "打造", "建设", "编码",
        "开发一个", "开发一套", "开发一款", "研发一个", "构建一个",
        "做一个", "做个", "做一套", "做一款", "写一个", "写个",
        "编一个", "建一个", "建个", "实现一个", "落地一个",
        "搭个", "搭一个", "写一篇", "设计一个",
    )

    # 产物名词之后紧跟的"非软件构建标的"领域专属词（评审第 6 轮 critical 修复）。
    # 当软件产物名词（如"软件"）后紧跟这些词时，产物名词只是该业务对象的修饰/标的，
    # 用户真实诉求属于对应专业业务（法律/著作权登记等），不应改判为软件研发。
    # 例："做个软件著作权登记"中"软件"后紧跟"著作权登记"，属法律登记业务。
    SOFTWARE_NOT_BUILD_TAILS: tuple = (
        "著作权", "版权", "知识产权", "专利", "商标",
        "登记", "注册", "维权", "许可", "授权", "合同", "合规",
        "行业", "产品方案", "市场", "营销", "推广",
    )

    # 业务域交付物/专业作业名词（对应各纯业务域单元的真实作业产出）。
    # 当这类名词出现在软件产物名词【之后】时，说明产物名词只是该业务作业的
    # 修饰语 / 手段 / 标的，而非用户要"构建"的软件对象 → 不判软件构建。
    # 反向场景（构建软件诉求中业务名词作软件主题、位于产物名词之前）不受影响，
    # 例如"开发一个数据分析工具"中"数据分析"在"工具"之前，仍正确判软件构建。
    DOMAIN_DELIVERABLE_TERMS: tuple = (
        # 法律咨询：审/起草合同、法律意见、合规、风险
        "审", "审查", "起草", "合同", "法务", "合规", "风险", "意见", "诉讼", "应诉",
        # 内容创作：文案/推文/稿件/运营/脚本
        "文案", "推文", "稿", "文章", "公众号", "短视频", "脚本", "营销", "运营", "润色", "排版",
        # 数据分析：报表/看板/分析/洞察/可视化
        "报表", "看板", "分析", "洞察", "可视化", "经营", "预测", "挖掘",
    )

    def __init__(self, registry: Optional[Registry] = None):
        self.registry = registry or Registry()

    def route(self, text: str) -> RouteResult:
        """对用户意图做多级路由判定"""
        if not text or not text.strip():
            return RouteResult(
                unit_id="", industry="", roles=[],
                confidence=0.0, needs_manual=True,
                fallback_reason="空输入"
            )

        # 第一步：全局行业单元评分（数据驱动）
        units = self.registry.all_units()
        if not units:
            return RouteResult(
                unit_id="", industry="", roles=[],
                confidence=0.0, needs_manual=True,
                fallback_reason="注册表为空，无可用单元"
            )

        # 计算每个单元的信号评分
        unit_scores = self._score_units(text, units)

        # 找到最高分单元（确定性 tie-break：同分时按 unit_id 字典序取小，
        # 不依赖注册文件加载/遍历顺序，保证路由归属稳定可复现）
        ranked_units = sorted(
            unit_scores.items(),
            key=lambda kv: (-kv[1]["score"], kv[0]),
        )
        best_unit_id = ranked_units[0][0] if ranked_units else ""
        best_score = unit_scores.get(best_unit_id, {}).get("score", 0.0)

        # 先检测软件构建意图（用于判定纯软件构建请求，即使无业务域信号命中也能路由）。
        # 评审 critical：软件产物构建意图联合判定。
        # 当用户诉求是"为某业务领域构建软件/系统/工具/APP/代码"时，业务领域名词
        # （如 合同/文案/数据分析）仅是软件的被构建对象，不应把诉求判给纯业务域单元
        # （否则 "开发一个合同管理系统" 会被误判为 法律咨询）。
        software_override = False
        sw_own_score = 0.0  # 软件研发单元自身的信号得分（仅凭 override 之外的真实软件信号）
        sw_unit_id = self._software_engineering_unit_id(units)
        is_sw_build_intent = self._is_software_build_intent(text)
        any_domain_hit = any(sc.get("score", 0) > 0 for sc in unit_scores.values())

        # 无任何行业信号命中时：若为明确软件构建意图（如"帮我做个官网"/"帮我搭个网站"），
        # 仍应路由到软件研发单元（其制品词已从行业别名收敛，岗位关键词未必能命中所有变体表达）
        if not best_unit_id or best_score <= 0:
            if sw_unit_id and is_sw_build_intent:
                best_unit_id = sw_unit_id
                best_score = 0.0
                software_override = True
            else:
                return RouteResult(
                    unit_id="", industry="", roles=[],
                    confidence=0.0, needs_manual=True,
                    fallback_reason="未命中任何行业单元"
                )
        elif sw_unit_id and is_sw_build_intent:
            if sw_unit_id != best_unit_id:
                # 最佳单元不是软件研发，但文本是"为某业务领域构建软件"：
                # 业务名词仅是软件被构建对象，改判到软件研发单元
                sw_own_score = unit_scores.get(sw_unit_id, {}).get("score", 0.0)
                best_unit_id = sw_unit_id
                best_score = sw_own_score
                software_override = True
            else:
                # 最佳单元已经是软件研发，但业务单元（如法律/营销）同步命中：
                # 需跳过歧义回落——业务名词仅是软件构建目标（如"写合同管理系统代码"），
                # 不应因业务侧同分而触发人工歧义确认
                software_override = True

        # 检查歧义：多个单元得分接近时需人工确认。
        # 规则：真正"跨行业冲突"必须满足——双方各自持有独立行业信号。
        # 若候选2的所有命中词均已被候选1命中（如泛化词"开发"在多个单元
        # 注册中重复出现），则仅属共享泛化词造成的伪歧义，不应回落人工。
        sorted_scores = sorted(unit_scores.items(),
                               key=lambda kv: (-kv[1]["score"], kv[0]))
        if not software_override and len(sorted_scores) >= 2:
            top1, top2 = sorted_scores[0], sorted_scores[1]
            top1_score = top1[1]["score"]
            top2_score = top2[1]["score"]
            if (top1_score > 0 and top2_score > 0
                    and top2_score / top1_score >= self.AMBIGUITY_RATIO_THRESHOLD):
                # 泛化共享词过滤：候选2若无独立命中词（其词集⊆候选1），
                # 说明二者仅因同一泛化词(如"开发")撞分 → 非真歧义
                top1_terms = set(top1[1].get("matched_terms", []))
                top2_terms = set(top2[1].get("matched_terms", []))
                if not (top2_terms - top1_terms):
                    pass  # 伪歧义：继续走正常路由，不做人工回落
                else:
                    unit_ids = [t[0] for t in sorted_scores[:2]]
                    return RouteResult(
                        unit_id="", industry="", roles=[],
                        confidence=0.2, is_ambiguous=True, needs_manual=True,
                        fallback_reason=f"行业归属存在歧义: {unit_ids}"
                    )

        unit = self.registry.get_unit(best_unit_id)
        if not unit:
            return RouteResult(
                unit_id="", industry="", roles=[],
                confidence=0.0, needs_manual=True,
                fallback_reason=f"单元不存在: {best_unit_id}"
            )

        # 在确定单元内识别岗位
        matched_roles = self._identify_roles(text, unit)

        if not matched_roles:
            # 软件构建诉求：即使未命中具体开发关键词（如"做一个文案类APP"），
            # 也明确落到软件研发单元的 developer（承接软件落地）岗位，而非仅"行业命中"。
            if software_override:
                dev = next((r for r in unit.roles if r.name == "developer"), None)
                if dev is not None:
                    matched_roles = [dev]
            if not matched_roles:
                # 行业命中但岗位未命中 → 路由到单元默认入口
                return RouteResult(
                    unit_id=unit.unit_id, industry=unit.industry,
                    roles=[], confidence=0.4,
                    matched_keywords={}, needs_manual=False,
                    fallback_reason="仅行业命中"
                )

        confidence = self._calc_confidence(text, unit, matched_roles)

        # 软件构建诉求已做决定性改判，且已明确落到具体岗位。
        # 评审 warning ②：若软件研发单元自身信号得分为 0（即除 override 改判外，
        # 文本未命中任何软件侧别名/能力/开发关键词，如"做一个文案类APP"这类只表达
        # "做一个软件"但未指明具体开发任务的弱信号诉求），不得仅凭 override 用 0 分
        # 覆盖 best_score 后仍强制抬到 0.6 静默自动放行，而应显著降置信 / 回落人工。
        # 仅当以下任一条件满足时，方可抬升置信度自动放行：
        #   - 软件研发单元自身有真实软件开发信号（sw_own_score>0，如命中了"开发"等岗位关键词）
        #   - 无任何行业单元命中信号（any_domain_hit=False）：此时无竞争领域，纯软件
        #     构建意图（含构建动词+软件产物名词）应直接自动路由，如"帮我做个公司官网"、
        #     "帮我搭个网站" 等——这些请求的制品词已从行业别名收敛，但仍属明确软件开发。
        if software_override and matched_roles and (
                sw_own_score > 0 or not any_domain_hit):
            confidence = max(confidence, 0.6)

        return RouteResult(
            unit_id=unit.unit_id,
            industry=unit.industry,
            roles=[r.name for r in matched_roles],
            confidence=confidence,
            matched_keywords={r.name: self._match_kw(text, r) for r in matched_roles},
            needs_manual=confidence < 0.4,
        )


    def cross_unit_candidates(self, text: str):
        """
        检测文本是否命中多个"具有独立信号"的行业单元（真跨行业诉求）。
        返回按得分降序的单元列表；若仅有伪歧义（共享泛化词）则返回空/单元素。
        """
        units = self.registry.all_units()
        if not units or not text or not text.strip():
            return []

        unit_scores = self._score_units(text, units)
        hits = [(uid, sc) for uid, sc in unit_scores.items() if sc["score"] > 0]
        hits.sort(key=lambda kv: kv[1]["score"], reverse=True)

        if len(hits) < 2:
            return [hits[0][0]] if hits else []

        top1_uid, top1_info = hits[0]
        top2_uid, top2_info = hits[1]

        # 与歧义判定一致：若候选2的命中词 ⊆ 候选1，则属泛化伪歧义 → 非真跨行业
        top1_terms = set(top1_info.get("matched_terms", []))
        top2_terms = set(top2_info.get("matched_terms", []))
        if not (top2_terms - top1_terms):
            return [top1_uid]

        # 真跨行业：返回所有有正分的候选（≥2个），供 cross-unit 编排
        return [uid for uid, _ in hits]

    def _score_units(self, text: str, units: List[IndustryUnit]) -> Dict[str, dict]:
        """
        数据驱动：对每个单元做多维信号评分。
        信号来源：industry_alias + capability_tags + role keywords。
        """
        scores = {}
        for unit in units:
            score = 0.0
            matched_signals = []
            matched_terms: List[str] = []  # 实际命中的词（用于歧义时区分泛化共享）

            # 1. 行业别名直接命中（强信号，2.0）
            for alias in unit.industry_alias:
                if alias and alias in text:
                    score += 2.0
                    matched_signals.append(f"alias:{alias}")
                    matched_terms.append(alias)

            # 2. capability_tags 命中（中信号，1.0）
            for tag in unit.capability_tags:
                if tag and tag in text:
                    score += 1.0
                    matched_signals.append(f"tag:{tag}")
                    matched_terms.append(tag)

            # 3. 单元内岗位关键词命中（强信号，1.5/岗位）
            for role in unit.roles:
                for kw in role.get_keywords():
                    if kw and kw in text:
                        score += 1.5
                        matched_signals.append(f"role:{role.name}:{kw}")
                        matched_terms.append(kw)
                        break  # 每岗位只计一次

            scores[unit.unit_id] = {
                "score": round(score, 2),
                "signals": matched_signals,
                "matched_terms": matched_terms,
                "unit": unit,
            }
        return scores

    def _identify_roles(self, text: str, unit: IndustryUnit) -> List[Role]:
        """识别文本对应单元内的哪些岗位被命中（可能多个=复合）
        数据驱动：使用单元注册声明中的关键词而非全局词典。
        """
        hits: List[Role] = []

        for r in unit.roles:
            kws = r.get_keywords()
            if self._match_any(text, kws):
                hits.append(r)

        # 按默认优先级排序（稳定确定性输出）
        hits.sort(key=lambda r: self._role_priority_index(r.name))
        return hits

    def _role_priority_index(self, role_name: str) -> int:
        if role_name in self.DEFAULT_ROLE_PRIORITY:
            return self.DEFAULT_ROLE_PRIORITY.index(role_name)
        return len(self.DEFAULT_ROLE_PRIORITY)

    def _software_engineering_unit_id(self, units: List[IndustryUnit]) -> str:
        """定位"软件研发"工程单元（跨行业通用能力层的软件落地基座）。"""
        for u in units:
            if u.industry and "软件" in u.industry:
                return u.unit_id
        # 兜底：岗位含 developer 的单元视作软件工程承载
        for u in units:
            if any(r.name == "developer" for r in u.roles):
                return u.unit_id
        return ""

    def _is_software_build_intent(self, text: str) -> bool:
        """判断文本是否表达"为某业务领域构建软件/系统/工具/代码/APP"的开发诉求。

        本实现是多次评审收敛后的稳健判定，需【同时】满足：
        1. 存在明确的"构建/开发"动作词（评审 critical ①）：
           排除副词用法 —— "系统的学一下法律/我要系统的掌握法律知识" 中"系统"
           =系统地（副词），并非软件产物；"软件产品要怎么推广" 是营销/内容诉求，
           这些均不含构建动词，不得改判软件研发。
        2. 命中软件产物名词，且该产物名词是句子的"软件构建目标"：
           - 产物名词之后若仍紧跟业务交付物/专业作业名词（如"APP推广文案"
             "数据分析工具出报表""软件采购合同""系统性的经营分析"），说明产物
             名词只是业务作业的修饰/手段/标的 → 不判软件构建。
           - 产物名词之后紧跟"非构建标的"领域专属词（著作权/登记/版权等，如
             "做个软件著作权登记"）→ 属法律等专业业务，不判软件构建。
           - 排除副词/所属修饰：产物名词后紧跟"地/的/化/性"等表副词、形容词化
             （如"系统地""平台化地""系统性"），该处产物名词非软件对象。
        任一位置满足即判软件构建（含所有产物名词出现的全部位置）。
        """
        if not text:
            return False
        # 1) 必须出现明确构建/开发动作词
        if not self._has_build_verb(text):
            return False
        # 2) 产物名词需在某处作为软件构建目标（遍历所有产物名词的全部出现位置）
        for term in self.SOFTWARE_BUILD_TERMS:
            if not term or term not in text:
                continue
            start = 0
            while True:
                pos = text.find(term, start)
                if pos < 0:
                    break
                after = pos + len(term)
                # 副词/所属修饰：产物名词后紧跟 地/的/化/性 → 非软件对象，跳过该处
                if after < len(text) and text[after] in ("地", "的", "化", "性"):
                    start = after
                    continue
                tail = text[after:]
                # 非构建标的（法律/著作权/登记…）：产物名词是专业业务标的 → 不判构建
                if self._tail_begins_non_build(tail):
                    start = after
                    continue
                # 产物名词之后仍有业务交付物名词 → 修饰/手段，非构建目标
                if not self._has_domain_deliverable(tail):
                    return True
                start = after
        return False

    def _has_build_verb(self, text: str) -> bool:
        """文本是否含明确的软件"构建/开发"动作词。"""
        return any(v and v in text for v in self.SOFTWARE_BUILD_VERBS)

    def _tail_begins_non_build(self, tail: str) -> bool:
        """产物名词之后的 tail 是否以"非软件构建标的"专业领域词开头。"""
        for tok in self.SOFTWARE_NOT_BUILD_TAILS:
            if tok and tail.startswith(tok):
                return True
        return False

    @staticmethod
    def _has_domain_deliverable(tail: str) -> bool:
        """判断产物名词之后(tail)是否仍出现业务域交付物/专业作业名词。

        评审 warning ④：DOMAIN_DELIVERABLE_TERMS 含单字/短词（审/稿/营…），
        直接做整串子串匹配可能对含该字的更长词（如"审核系统"里的"审"）过度拦截，
        从而误杀合法的软件构建诉求。故对【单字】词项做"独立成词"判断：仅当该字在
        tail 中作为相对独立词元出现（不被夹在两侧均为汉字的长词中间）时才视为命中，
        复合词项（>=2 字）仍按子串匹配。
        """
        if not tail:
            return False
        for dd in IntentRouter.DOMAIN_DELIVERABLE_TERMS:
            if not dd:
                continue
            if len(dd) == 1:
                if IntentRouter._single_char_standalone(dd, tail):
                    return True
            else:
                if dd in tail:
                    return True
        return False

    @staticmethod
    def _single_char_standalone(ch: str, tail: str) -> bool:
        """单字业务词是否在 tail 中以独立词元出现（未被两侧汉字夹成更长词的一部分）。"""
        idx = tail.find(ch)
        while idx != -1:
            prev_han = idx > 0 and '一' <= tail[idx - 1] <= '鿿'
            next_han = idx + 1 < len(tail) and '一' <= tail[idx + 1] <= '鿿'
            # 两侧均被汉字夹住（如"审"在"审核"中间位置被两汉字夹）→ 属长词一部分，非独立词元
            if not (prev_han and next_han):
                return True
            idx = tail.find(ch, idx + 1)
        return False

    def _match_any(self, text: str, keywords: List[str]) -> bool:
        for kw in keywords:
            if kw and kw in text:
                return True
        return False

    def _match_kw(self, text: str, role: Role) -> List[str]:
        """返回文本中命中该角色的关键词"""
        return [kw for kw in role.get_keywords() if kw and kw in text]

    def _calc_confidence(self, text: str, unit: IndustryUnit,
                         roles: List[Role]) -> float:
        """置信度计算：行业命中 + 岗位命中共同决定
        关键规则：只要明确命中了行业单元且岗位，基础置信度 >= 0.5（可路由），
        通过多维信号叠加提高置信度。仅在行业/岗位信息模糊时才需人工。
        """
        base = 0.0

        # 岗位命中保证分：只要有岗位命中即+0.3
        if roles:
            base += 0.3

        # 行业层面信号（叠加）
        for alias in unit.industry_alias:
            if alias and alias in text:
                base += 0.25
        for tag in unit.capability_tags:
            if tag and tag in text:
                base += 0.15

        # 岗位层面信号（每岗位可叠加）
        for r in roles:
            kws = self._match_kw(text, r)
            if kws:
                base += 0.1 * min(len(kws), 3)

        return round(min(base, 1.0), 2)


class CompositePlanner:
    """
    M4 会话编排判定 + M6 复合agent装配器

    包含评审补强① 的 role_priority + boundary 规则：
    - 同行业多岗位复合：按 role_priority 依赖序装配
    - role 间通过交接卡传递产物，不互相污染记忆
    """

    # 默认复合装配的 role 优先执行顺序
    # 架构定方案先行，开发在后，评审在最后（符合"架构→开发→评审"链路）
    COMPOSITE_ORDER: Dict[str, int] = {
        "secretary": 0,
        "product": 1,
        "architect": 2,
        "game_planner": 2,
        "level_designer": 3,
        "developer": 4,
        "game_dev": 4,
        "reviewer": 5,
    }

    def __init__(self, registry: Optional[Registry] = None,
                 handoff_bus=None):
        self.registry = registry or Registry()
        # 注入交接总线（用于 M5 跨单元交接自动建卡）
        self.handoff_bus = handoff_bus
        if self.handoff_bus is None:
            try:
                from .handoff import HandoffBus
                self.handoff_bus = HandoffBus()
            except Exception:
                self.handoff_bus = None

    def plan(self, text: str) -> dict:
        """根据路由结果决定会话编排方案（内部路由一次后交 plan_from_result）"""
        router = IntentRouter(self.registry)
        result = router.route(text)
        return self.plan_from_result(result, text)

    def plan_from_result(self, result: "RouteResult", text: str) -> dict:
        """由已算好的路由结果决定会话编排方案。

        与 plan() 的区别：本方法不再重复做意图路由，直接基于传入的
        RouteResult 编排，避免同一意图被 route 两次（消除重复识别）。
        """
        if result.needs_manual:
            return {
                "mode": "manual",
                "reason": result.fallback_reason,
                "message": f"置信度不足，回落 L2 人工确认。意图: {text}",
            }

        unit = self.registry.get_unit(result.unit_id)
        if not unit:
            return {"mode": "error", "message": f"单元不存在: {result.unit_id}"}

        hit_roles = [unit.role_by_name(r) for r in result.roles if unit.role_by_name(r)]

        if not hit_roles:
            # 仅行业命中
            return {
                "mode": "unit_default",
                "unit_id": unit.unit_id,
                "industry": unit.industry,
                "message": f"仅命中行业 {unit.industry}，路由到 {unit.unit_id} 默认入口",
            }

        if len(hit_roles) == 1:
            # 单直连
            role = hit_roles[0]
            return {
                "mode": "direct",
                "unit_id": unit.unit_id,
                "industry": unit.industry,
                "role": role.name,
                "role_prefix": role.prefix,
                "session_prefix": role.prefix,
                "message": f"单直连 → {unit.unit_id}@{role.name}",
            }

        # 多岗位 → 复合装配判定
        all_comp = all(r.composite for r in hit_roles)
        if all_comp:
            # 按 COMPOSITE_ORDER 依赖序排列（role_priority 规则）
            ordered = sorted(hit_roles, key=lambda r: self.COMPOSITE_ORDER.get(r.name, 99))
            ordered_names = [r.name for r in ordered]
            prefixes = [r.prefix for r in ordered]
            return {
                "mode": "composite",
                "unit_id": unit.unit_id,
                "industry": unit.industry,
                "roles": ordered_names,
                "session_prefix_set": prefixes,
                "message": f"复合装配: {unit.unit_id} 同session并装岗位 {ordered_names}",
                "execution_order": ordered_names,
                # boundary 规则：岗位间仅经交接卡传递产物，不互相污染记忆
                "boundary": {
                    "role_isolation": "handoff_card_only",
                    "execution_order": ordered_names,
                    "rule": "architecture_before_dev_before_review",
                },
            }
        else:
            # 含不可复合岗位 → 需拆 session 走交接
            # M5：自动创建交接卡（而非仅提示）
            msg = "命中岗位含不可复合项，需拆新session经 M5 交接卡接力"
            card = None
            if self.handoff_bus:
                try:
                    card = self.handoff_bus.create_handoff(
                        source_unit=unit.unit_id,
                        target_unit=unit.unit_id,
                        intent=text,
                        context=f"角色 {[r.name for r in hit_roles]} 含不可复合岗位，需要交接接力",
                    )
                    msg += f" [交接卡已自动创建: {card.id}]"
                except Exception:
                    pass
            return {
                "mode": "handoff_required",
                "unit_id": unit.unit_id,
                "industry": unit.industry,
                "roles": [r.name for r in hit_roles],
                "message": msg,
                "handoff_required": True,
                "handoff_card_id": card.id if card else None,
            }

    def plan_cross_unit(self, text: str,
                        source_unit_id: str, target_unit_id: str) -> dict:
        """
        M5 跨单元交接编排：
        当一个意图命中了两个不同行业的单元时，
        自动创建交接卡，将任务拆分到各自的新 session 处理。
        """
        source = self.registry.get_unit(source_unit_id)
        target = self.registry.get_unit(target_unit_id)
        if not source or not target:
            return {"mode": "error", "message": "交接目标单元不存在"}

        card = None
        if self.handoff_bus:
            card = self.handoff_bus.create_handoff(
                source_unit=source_unit_id,
                target_unit=target_unit_id,
                intent=text,
                context=(
                    f"跨行业复合诉求，拆分到 {source.industry} 和 "
                    f"{target.industry} 各自的新 session 执行"
                ),
            )

        return {
            "mode": "cross_unit_handoff",
            "source_unit": source_unit_id,
            "target_unit": target_unit_id,
            "message": (
                f"跨行业复合: {source.unit_id}({source.industry}) → "
                f"{target.unit_id}({target.industry}) 需拆新session分别执行"
            ),
            "handoff_card_id": card.id if card else None,
        }
