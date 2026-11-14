"""industry-db 命令：行业分区定义库查询 / 自检 / 导出。"""
from __future__ import annotations

import csv
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from hanghang.engine import industry_schema
from hanghang.engine.industry_db import GDP_KINDS, IndustryDatabase
from hanghang.engine.money_flow import FLOW_KINDS, RECONCILE_TOLERANCE
from hanghang.engine.scale_ledger import METRIC_LABELS, SCALE_METRICS


def _db(args):
    data_dir = getattr(args, "data_dir", "") or None
    return IndustryDatabase(data_dir=data_dir)


def _views_label(db, occ_id: str) -> str:
    """职业被哪些视角引用（按权重降序，权重 < 1 标 *）。

    归属是模糊的，所以这里不挑一个"主分区"假装它只有一处：
    一个职业挂几处就列几处，没挂的说清楚是"还没被聚类看上"。
    """
    edges = db.views_of_occupation(occ_id)
    if not edges:
        return "未挂视角"
    ranked = sorted(edges, key=lambda m: (-db.axis_view._weight(m),
                                          m.get("partition", "")))
    return "、".join(m.get("partition", "")
                     + ("*" if db.axis_view._weight(m) < 0.999 else "")
                     for m in ranked)


def _planned_role_label(db, pid: str, role: str) -> str:
    """骨架里的岗位名 → 能反查到中文就带上，反查不到原样给出。

    岗位名是**分区内命名**，只认本分区的边：拿别处的同名边背书，等于
    允许"凭空加一个别处在用的名字"。反查结果与第 19 条校验同一口径。
    """
    for m in db.axis_view.of_partition(pid):
        if (m.get("unit_role") or "") != role:
            continue
        o = db.occupation(m.get("occupation", ""))
        if o:
            return f"{role}({o.get('name')})"
    return role


def cmd_industry_partitions(args):
    """列出分区定义表（按产值降序，0 表示全部）"""
    db = _db(args)
    print(db.render_text(top=getattr(args, "top", 0) or 0))


def cmd_industry_partition(args):
    """查看单个分区详情：聚类依据/付费方/供给结构/成员职业"""
    db = _db(args)
    p = db.partition(args.id)
    if not p:
        print(f"未找到分区: {args.id}")
        print("可用分区: " + ", ".join(x.get("id", "") for x in db.partitions))
        return
    gdp = p.get("gdp_cny")
    print(f"■ {p.get('name')} ({p.get('id')})  状态={p.get('status')}"
          f"  优先级={p.get('priority')}")
    if p.get("aliases"):
        print("  别名: " + "、".join(p["aliases"]))
    print("  聚类依据: " + "、".join(p.get("cluster_basis", [])))
    print("  付费方: " + "、".join(p.get("demand_side", [])))
    members = db.members_of(p.get("id", ""))
    # provider_mix 的契约是"成员职业实测"，无成员分区它就是 0/0/0；
    # 人工估算单独存在 provider_mix_estimated，只用于标注 ~ 展示，不与实测混读。
    estimated = p.get("provider_mix_estimated") or {}
    if members:
        mix = db.provider_distribution(members)
        print(f"  供给结构(实测): AI {mix['ai']}% / 混合 {mix['hybrid']}%"
              f" / 纯人 {mix['human']}%  (n={mix['n']})")
        if estimated:
            print(f"  对账留档(原估算): AI {estimated.get('ai', '-')}% / "
                  f"混合 {estimated.get('hybrid', '-')}% / "
                  f"纯人 {estimated.get('human', '-')}%")
    elif estimated:
        # 无成员职业 = 无实测数据，只展示人工估算并标 ~，不伪装成实测
        print(f"  供给结构(估算~，无成员职业): AI {estimated.get('ai', '-')}% / "
              f"混合 {estimated.get('hybrid', '-')}% / "
              f"纯人 {estimated.get('human', '-')}%")
    else:
        print("  供给结构: 无成员职业，也无人工估算")
    # 承接通道：不付费 ≠ 不值得分析，这里把"从哪条路进来"摊开
    sides = db.access_distribution(members) if members else None
    if sides and sides.get("n"):
        print(f"  承接通道(实测 n={sides['n']}): "
              + " / ".join(f"{k} {sides[k]}%"
                           for k in ("paid_direct", "non_market",
                                     "org_internal", "household")
                           if sides.get(k)))
    emp = p.get("employment")
    print(f"  从业人员: {f'{emp} 万人' if emp is not None else '无就业口径'}"
          + (f"（{p['employment_source']}）" if p.get("employment_source") else ""))
    print(f"  视角: {'/'.join(db.axes_of(p))}")
    # gdp 可能是字符串（脏数据）：只读命令不该因此 traceback。
    # 类型错由 industry check 第 17-b 条报，这里按"无口径"展示。
    gdp_num = gdp if isinstance(gdp, (int, float)) and not isinstance(gdp, bool) else None
    print(f"  年产值: {f'{gdp_num / 1e8:,.0f} 亿元' if gdp_num else '无市场口径(刻意留空)'}")
    # 口径类型必须跟着数一起露脸：只说"2.5 万亿"不说是什么口径，
    # 下游拿去和增加值并列就会把 GMV 当成 GDP。
    kind = p.get("gdp_kind") or "未标口径"
    conf = p.get("gdp_confidence")
    print(f"  产值口径类型: {kind}"
          + (f"（{GDP_KINDS[kind]}）" if kind in GDP_KINDS else "")
          + (f"  置信度={conf}" if conf else ""))
    if p.get("gdp_scope"):
        print(f"  产值口径说明: {p['gdp_scope']}")
    if p.get("gdp_source"):
        print(f"  来源: {p['gdp_source']}")
    print(f"  单元: {p.get('unit_id') or '未建'}")
    edges = db.axis_view.of_partition(p.get("id", ""))
    if edges:
        mix = db.axis_view.axis_mix(p.get("id", ""))
        print("  视角边: " + "、".join(f"{k} {v}" for k, v in mix.items() if v)
              + "（同一职业可同时被多个视角引用，权重不代表概率）")
    if p.get("channels"):
        print("  数据渠道: " + "、".join(p["channels"]))
    if p.get("note"):
        print(f"  备注: {p['note']}")
    planned = p.get("planned_roles", []) or []
    if planned and not p.get("unit_id"):
        # 骨架里存的是 unit_role（岗位名），直接打印等于给内部命名；
        # 能反查到职业就带中文名，反查不到原样给出，方便对齐
        named = [_planned_role_label(db, p.get("id", ""), r) for r in planned]
        print("  计划岗位(骨架): " + "、".join(named))
    if members:
        weights = db.weights_of(p.get("id", ""))
        print(f"  成员职业({len(members)}，按权重降序):")
        for o in members:
            flag = "基线" if o.get("baseline_occupation") else "扩展"
            w = weights.get(o.get("id"), 1.0)
            # 权重 < 1 说明"这份活只是顺带干"，不是归属不合格
            wtxt = "1.00" if w >= 0.999 else f" {w:.2f}"
            print("    - " + db._pad(o.get("code", "-"), 12)
                  + db._pad(o.get("id", ""), 26)
                  + db._pad(o.get("name", ""), 20)
                  + db._pad(o.get("provider", "-"), 8) + wtxt + " " + flag)
    else:
        print("  成员职业: 该视角下筛不出职业（不是缺口，是这个角度看过去没人）")


def cmd_industry_axis(args):
    """按视角看同一批分区：职业 / 行业 / 税收 / 产出。

    一个分区可以被多根轴同时引用，所以这不是"换个筛选器"，而是换一个问题：
      occupation 这根分区里的人在干什么活（数字员工接不接得住）
      industry   这家单位在卖什么（GB/T 4754 口径、产值归口）
      tax        这笔钱按什么税目征（跟交付物走，不跟行业走）
      output     一年多大产值、多少人就业（gdp_cny + employment）
    """
    from hanghang.engine.industry_db import AXES
    db = _db(args)
    axis = (getattr(args, "axis", "") or "").strip()
    if axis and axis not in AXES:
        print(f"未知视角: {axis}（合法 {list(AXES)}）")
        sys.exit(1)

    snap = db.compute()
    rows = snap["rows"]
    if axis:
        rows = [r for r in rows if axis in r["axes"]]
        head = {"occupation": "职业视角：这些分区里的人在干什么活",
                "industry": "行业视角：这些单位在卖什么",
                "tax": "税收视角：这笔钱按什么税目征",
                "output": "产出视角：多大产值、多少人就业"}[axis]
    else:
        head = "四根轴全景：同一个分区可以同时出现在多根轴下"
    print("=" * 78)
    print(head)
    print("-" * 78)
    for r in rows:
        mark = {"covered": "已建", "pending": "待建",
                "evaluated": "不建"}.get(r["status"], r["status"])
        if axis == "output":
            _g = r.get("gdp_cny")
            _g = _g if isinstance(_g, (int, float)) and not isinstance(_g, bool) else None
            gdp = f"{_g / 1e8:,.0f}亿" if _g else "无口径"
            emp = f"{r['employment']}万人" if r.get("employment") is not None else "无就业口径"
            print(db._cell(mark, 5) + db._cell(r["name"], 22)
                  + db._cell(gdp, 12) + db._cell(emp, 12)
                  + "、".join(r["demand_side"])[:26])
        elif axis == "tax":
            print(db._cell(mark, 5) + db._cell(r["name"], 22)
                  + "税目口径未接入(见 reference sources --axis tax)"
                  f"  付费方: {'、'.join(r['demand_side'])[:30]}")
        else:
            mix = r["access_mix"] or {}
            side = "、".join(f"{k}{mix.get(k, 0)}%" for k in
                             ("paid_direct", "non_market", "org_internal", "household")
                             if mix.get(k))
            print(db._cell(mark, 5) + db._cell(r["name"], 22)
                  + db._cell(f"{r['member_count']}职业", 8)
                  + f"通道: {side or '-'}")
    print("-" * 78)
    print(f"样本 {len(rows)} 个分区（缺省四轴都可见；axes 字段可按分区收窄）")
    print("=" * 78)


def cmd_industry_access(args):
    """按需求侧承接通道看职业：现金市场 / 非市场(财政) / 企业内部 / 家庭无酬。

    这张表专门回答"哪些职业不靠终端用户直接付费"——不付费不等于不值得分析：
    财政供养和家庭无酬同样构成需求与人群画像，只是承接通道不同。
    """
    from hanghang.engine.industry_db import ACCESS_SIDES, DEFAULT_ACCESS
    db = _db(args)
    snap = db.compute()
    side = (getattr(args, "side", "") or "").strip()
    if side and side not in ACCESS_SIDES:
        print(f"未知通道: {side}（合法 {list(ACCESS_SIDES)}）")
        sys.exit(1)

    mix = snap["access_mix"]
    print("=" * 78)
    print(f"需求侧承接通道（{snap['access_mix_n']} 个已挂分区职业实测；"
          f"字段不写 = {DEFAULT_ACCESS}）")
    print("-" * 78)
    for k in ACCESS_SIDES:
        print(f"  {k:<14}{mix.get(k, 0):>6}%   {_ACCESS_DESC[k]}")
    print("-" * 78)
    rows = db.occupations if not side else [o for o in db.occupations
                                            if db.access_of(o) == side]
    print(f"{'职业':<16}{'名称':<14}{'视角':<18}{'通道':<14}计费")
    for o in rows:
        print(f"{o.get('id', ''):<16}{o.get('name', '')[:12]:<14}"
              f"{_views_label(db, o.get('id', '')):<18}{db.access_of(o):<14}"
              f"{o.get('billing', '-')}")
    print(f"\n合计 {len(rows)} 个职业"
          f"（覆盖分母只算 baseline_occupation，本表是全量登记）")
    print("=" * 78)


_ACCESS_DESC = {
    "paid_direct": "服务本身直接收费（现金市场，缺省）",
    "non_market": "财政/公共预算供养，终端用户不付费（≠ 不值得分析）",
    "org_internal": "企业内部职能，需求侧=雇主预算",
    "household": "家庭无酬劳动，无现金交易但是真实劳动时间",
}


def cmd_industry_occupations(args):
    """列出职业（可按分区/提供者/收费方式过滤）

    过滤走 **视角边**，不读职业身上的归属字段 —— 软归属改造后职业已经没有
    `unit_id` 了：一个职业挂几处是几条边，原子岗位本身不带"我在哪个分区"。
    """
    db = _db(args)
    rows = list(db.occupations)
    part = getattr(args, "partition", "") or ""
    if part:
        if not db.partition(part):
            print(f"未找到分区: {part}")
            print("可用分区: " + ", ".join(x.get("id", "") for x in db.partitions))
            sys.exit(1)
        rows = db.members_of(part)
    if getattr(args, "provider", ""):
        rows = [o for o in rows if o.get("provider") == args.provider]
    if getattr(args, "billing", ""):
        rows = [o for o in rows if o.get("billing") == args.billing]
    if getattr(args, "access", ""):
        rows = [o for o in rows if db.access_of(o) == args.access]
    if getattr(args, "unassigned", False):
        # 未被任何视角引用（不是"字段为空"——那个字段已经不存在了）
        free = {o.get("id") for o in db.unassigned_occupations()}
        rows = [o for o in rows if o.get("id") in free]
    if not rows:
        print("无匹配职业")
        return
    print(f"{'职业ID':<26}{'名称':<14}{'视角':<24}{'交付物':<8}{'提供者':<8}"
          f"{'收费':<12}{'大典编码':<13}基线")
    for o in rows:
        views = _views_label(db, o.get("id", ""))
        gb = db.catalog.gb_code_of(o.get("id", "")) if db.catalog else ""
        print(f"{o.get('id', ''):<26}{o.get('name', ''):<14}{views:<24}"
              f"{o.get('deliverable', '-'):<8}{o.get('provider', '-'):<8}"
              f"{o.get('billing', '-'):<12}{gb or '-':<13}"
              f"{'是' if o.get('baseline_occupation') else '否'}")
    mapped = sum(1 for o in rows
                 if db.catalog and db.catalog.gb_code_of(o.get("id", "")))
    head = f"\n合计 {len(rows)} 个职业"
    if part:
        head += f"（分区 {part} 视角下筛出；同一职业可能同时出现在别的分区）"
    elif getattr(args, "unassigned", False):
        head += "（未挂任何视角；不是缺口，是还没被任何聚类看上）"
    print(head + (f"，其中 {mapped} 个已挂大典编码" if db.catalog else ""))


def cmd_industry_occupation(args):
    """看一个职业被哪些视角引用过：这是"多归属"的正面表达。

    单值归属时代这里只能打印一个分区；现在会列出所有视角与权重，
    并标出权重 >= 0.5 的主要归属。职业本身没有任何归属字段——
    改分区、拆分区、重命名都不会动到这条记录。
    """
    db = _db(args)
    o = db.occupation(args.id)
    if not o:
        by_code = db.axis_view._occ_by_code.get(args.id.upper())
        o = by_code
    if not o:
        print(f"未找到职业: {args.id}（slug 或 OCC-编号均可）")
        return
    gb = db.catalog.gb_code_of(o.get("id", "")) if db.catalog else ""
    print(f"■ {o.get('code', '-')}  {o.get('name')}  ({o.get('id')})")
    print(f"  交付物: {o.get('deliverable', '-')}   提供者: {o.get('provider', '-')}"
          f"   收费: {o.get('billing', '-')}   通道: {db.access_of(o)}")
    print(f"  基线: {'是（进覆盖分母）' if o.get('baseline_occupation') else '否'}"
          f"   大典编码: {gb or '-'}")
    if o.get("note"):
        print(f"  备注: {o['note']}")
    edges = db.views_of_occupation(o.get("id", ""))
    if not edges:
        print("  视角: 无 —— 这个岗位还没被任何聚类看上（不是缺口，原子岗位不靠归属活着）")
        return
    print(f"  视角({len(edges)}，权重不是概率，也不要求相加为 100):")
    for m in sorted(edges, key=lambda x: (-db.axis_view._weight(x),
                                          x.get("partition", ""))):
        w = db.axis_view._weight(m)
        part = db.partition(m.get("partition", "")) or {}
        mark = "主要" if w >= 0.5 else "次要"
        role = f"  岗位名={m['unit_role']}" if m.get("unit_role") else ""
        print(f"    - {db._pad(m.get('partition', ''), 24)}"
              f"{db._pad(part.get('name', '(未登记)'), 20)}"
              f"轴={db._pad(m.get('axis', ''), 12)}权重={w:.2f} {mark}{role}")


def cmd_industry_filter(args):
    """筛选器语义：按任意维度组合筛职业，不需要先决定"归到哪"。

    这就是"分类是筛选器不是户籍"的落地形态 —— 同一个职业会因为条件不同
    出现在不同结果里，没有哪个结果是"它的正确归属"。
    """
    db = _db(args)
    min_w = float(getattr(args, "min_weight", 0) or 0)
    rows = db.axis_view.filter(
        partition=getattr(args, "partition", "") or "",
        axis=getattr(args, "axis", "") or "",
        provider=getattr(args, "provider", "") or "",
        billing=getattr(args, "billing", "") or "",
        access=getattr(args, "access", "") or "",
        deliverable=getattr(args, "deliverable", "") or "",
        min_weight=min_w,
        baseline_only=getattr(args, "baseline_only", False))
    cond = " ".join(f"{k}={v}" for k, v in {
        "分区": getattr(args, "partition", ""), "轴": getattr(args, "axis", ""),
        "提供者": getattr(args, "provider", ""), "收费": getattr(args, "billing", ""),
        "通道": getattr(args, "access", ""), "交付物": getattr(args, "deliverable", ""),
        "基线": "是" if getattr(args, "baseline_only", False) else "",
    }.items() if v)
    print("=" * 78)
    print(f"筛选: {cond or '(无条件)'}"
          + (f"  权重>={min_w}" if min_w else ""))
    print("-" * 78)
    if not rows:
        print("无匹配职业")
    for o in rows:
        views = "、".join(sorted({m.get("partition", "") for m in
                                  db.views_of_occupation(o.get("id", ""))}))
        print(f"{db._pad(o.get('code', '-'), 12)}"
              f"{db._pad(o.get('id', ''), 26)}"
              f"{db._pad(o.get('name', ''), 18)}"
              f"{db._pad(o.get('provider', '-'), 7)}"
              f"视角: {views or '-'}")
    print("-" * 78)
    print(f"命中 {len(rows)} 个职业（同一职业在不同条件下可重复出现，这不是重复登记）")
    print("=" * 78)


def cmd_industry_catalog(args):
    """查《职业分类大典（2022 年版）》参考表：编码/名称检索，或看覆盖快照。

    "职业编码"指大典的细类编码（大类-中类-小类-细类，如 4-14-02-02）。
    """
    db = _db(args)
    cat = db.catalog
    if cat is None:
        print("未加载职业大典参考表：data/reference/occupation-catalog-2022.yaml")
        sys.exit(1)

    kw = getattr(args, "search", "") or ""
    code = getattr(args, "code", "") or ""
    major = getattr(args, "major", "") or ""
    gaps = getattr(args, "gaps", False)
    limit = getattr(args, "limit", 20) or 0

    if code:
        e = cat.entry(code)
        if not e:
            print(f"未找到大典编码: {code}")
            sys.exit(1)
        print(f"■ {e.get('code')} {e.get('name')}")
        print(f"  归属: {cat.path_of(code)}")
        if e.get("gbm"):
            print(f"  GBM 码: GBM{e['gbm']}")
        marks = e.get("marks") or []
        if marks:
            tag = {"L": "绿色职业", "S": "数字职业"}
            print("  标记: " + "、".join(tag.get(m, m) for m in marks))
        if e.get("desc"):
            print(f"  描述: {e['desc']}")
        owners = [o for o in db.occupations
                  if cat.gb_code_of(o.get("id", "")) == code]
        if owners:
            print("  已挂到我们职业库的:")
            for o in owners:
                print(f"    - {o.get('id'):<24}{o.get('name', '')}"
                      f"  [{_views_label(db, o.get('id', ''))}]")
        else:
            print("  已挂到我们职业库的: 无（该细类尚无对应行业职业）")
        return

    if kw:
        hits = cat.search(kw, limit=limit)
        if not hits:
            print(f"大典里没有名称含「{kw}」的细类职业")
            return
        print(f"{'编码':<14}{'名称':<26}{'归属':<40}标记")
        for e in hits:
            marks = "/".join(x for x in ("L" if "L" in (e.get("marks") or []) else "",
                                         "S" if "S" in (e.get("marks") or []) else "") if x)
            print(f"{e.get('code', ''):<14}{e.get('name', '')[:24]:<26}"
                  f"{cat.path_of(e.get('code', ''))[:38]:<40}{marks or '-'}")
        print(f"\n命中 {len(hits)} 条（--limit 0 看全部）")
        return

    if gaps:
        ids = [o.get("id", "") for o in db.occupations]
        rows = cat.unmapped_gaps(ids, major=major, limit=limit)
        print(f"{'编码':<14}{'名称':<26}归属")
        for e in rows:
            print(f"{e.get('code', ''):<14}{e.get('name', '')[:24]:<26}"
                  f"{cat.path_of(e.get('code', ''))[:38]}")
        print(f"\n未挂大典细类 {len(rows)} 条"
              f"（这是候选池：大典全集不进分母；军队人员/采矿工种这类不是不登记，"
              f"而是用 industry access 区分承接通道、由分区 status 单独回答要不要建单元）")
        return

    print(cat.render_coverage([o.get("id", "") for o in db.occupations]))


def cmd_industry_scale(args):
    """六口径规模账：盈利/资产/估值/从业/资源消耗/产值，谁有数谁说话。

    这份账存在的唯一理由：**大行业不该因为产值没统计就整体隐身**。
    产值是最难拿的一格，但利润、资产、市值、人数、能耗都在别处留着痕迹；
    只要任一口径有数，这个行业就还在表里，能排序、能比较、能进分母。
    """
    db = _db(args)
    sl = db.scales
    part = getattr(args, "partition", "") or ""
    if part:
        if not db.partition(part):
            print(f"未找到分区: {part}")
            sys.exit(1)
        vis = sl.visibility(part)
        p = db.partition(part) or {}
        print(f"■ {p.get('name')} ({part})  六口径 {vis['count']}/6"
              f"  等级={vis['level']}")
        print("-" * 78)
        for m in SCALE_METRICS:
            rec = sl.metric(part, m)
            label = METRIC_LABELS[m]
            if rec is None:
                why = sl.missing_reason(part, m) or "未填原因"
                print(f"  {label:<12} —        {why}")
                continue
            # 数值缺失时绝不能把 None 送进 f-string 的 ":,.0f" —— 那会 TypeError，
            # 而这是只读命令：一份脏数据不该让看数据的人拿到 traceback。
            # 缺值按"这一格是空的 + 原因"走，与 rec is None 同一条路。
            amount = sl._amount(rec, m)
            if amount is None:
                why = sl.missing_reason(part, m) or "数值缺失（键写错或没填）"
                print(f"  {label:<12} —        {why}")
                continue
            if m == "employment":
                val = f"{amount:,.0f} 万人"
            elif m == "resource":
                val = sl.human_resource(amount, rec.get("unit", ""))
            else:
                val = f"{amount / 1e8:,.0f} 亿元"
            extra = []
            if rec.get("kind"):
                extra.append(f"口径={rec['kind']}")
            if rec.get("confidence"):
                extra.append(f"置信={rec['confidence']}")
            print(f"  {label:<12} {val:<16} {'  '.join(extra)}")
            if rec.get("basis"):
                print(f"  {'':<12} {rec['basis']}")
            if rec.get("source"):
                print(f"  {'':<12} 来源: {rec['source']}")
        return

    rows = sl.visibility_all()
    only = getattr(args, "only", "") or ""
    if getattr(args, "gaps", False):
        only = "hidden"
    if only:
        rows = [r for r in rows if r["level"] == only]
    top = getattr(args, "top", 0) or 0
    if top:
        rows = rows[:top]

    counts = {lv: sum(1 for r in sl.visibility_all() if r["level"] == lv)
              for lv in ("full", "partial", "hidden")}
    print("=" * 92)
    print(f"行业规模账 · 六口径可见度  v{sl.version}"
          f"  口径年份 {sl.year_basis or '-'}  updated {sl.updated_at}")
    print("-" * 92)
    print(f"分区 {sum(counts.values())} 个：看清大半(full) {counts['full']}"
          f" / 至少一面可见(partial) {counts['partial']}"
          f" / 全空(hidden) {counts['hidden']}")
    print("立场: 一个行业只要**任一**口径有数就没隐身；产值只是六格之一。"
          "缺格逐条写着为什么缺。")
    print("-" * 92)
    head = (db._cell("分区", 22) + db._cell("口径", 7)
            + db._cell("gdp", 6) + db._cell("就业", 6) + db._cell("利润", 6)
            + db._cell("资产", 6) + db._cell("估值", 6) + db._cell("资源", 6))
    print(head + "等级")
    for r in rows:
        p = db.partition(r["partition"]) or {}
        cells = "".join(db._cell("●" if m in r["present"] else "·", 6)
                        for m in ("gdp", "employment", "profit",
                                  "asset", "valuation", "resource"))
        print(db._cell(p.get("name", r["partition"]), 22)
              + db._cell(f"{r['count']}/6", 7) + cells
              + {"full": "full", "partial": "part",
                 "hidden": "HIDDEN"}[r["level"]])
    if only == "hidden" and rows:
        print("-" * 92)
        print("全空分区逐格原因（说不出总量又不说什么缺 = 保证会漏）：")
        for r in rows:
            for m, why in r["missing_detail"].items():
                print(f"  {db._cell(r['partition'], 22)}{db._cell(m, 12)}{why}")
    print("-" * 92)
    print("● = 该口径有数，· = 该口径空（原因见 missing）；"
          "`industry scale --partition <id>` 看单分区全貌，"
          "`--gaps` 只看全空分区")
    print("=" * 92)


def cmd_industry_money(args):
    """资金流守恒账：钱从哪来、经谁的手、沉在哪里。

    双边记账让「全局流入 = 全局流出」变成恒等式（不是校验点）——真正能抓漏的是
    **节点与外部口径对账**：图里画出来的边求和，与居民可支配收入/一般公共预算
    收入这类权威总量对不上，就说明还有流向没画出来。
    """
    db = _db(args)
    book = db.money
    node = getattr(args, "node", "") or ""
    if node:
        n = book.node(node)
        if not n:
            print(f"未找到节点: {node}")
            print("可用节点: " + ", ".join(book.node_ids()))
            sys.exit(1)
        pos = book.position(node)
        print(f"■ {n.get('name')} ({node})  类型={n.get('type')}"
              + (f"  部门={n['sector']}" if n.get("sector") else ""))
        print(f"  流入 {pos['inflow'] / 1e8:,.0f} 亿  "
              f"流出 {pos['outflow'] / 1e8:,.0f} 亿  "
              f"净额 {pos['net'] / 1e8:,.0f} 亿"
              f"  （其中 {pos['unknown_edges']} 条边数额待补）")
        if n.get("source"):
            print(f"  对账口径: {n['source']}")
        for side, label in (("in", "流入"), ("out", "流出")):
            declared = n.get(f"declared_{side}_cny")
            if declared is None:
                print(f"  {label}对账: 未声明外部总量（缺口见 unobserved）")
                continue
            traced = pos["inflow"] if side == "in" else pos["outflow"]
            gap = traced - declared
            ratio = abs(gap) / declared if declared else 0
            print(f"  {label}对账: 图中 {traced / 1e8:,.0f} 亿 / 外部 "
                  f"{declared / 1e8:,.0f} 亿  差额 {gap / 1e8:+,.0f} 亿"
                  f"（{ratio:.1%}，容差 {RECONCILE_TOLERANCE:.0%}）"
                  + ("  ✓" if ratio <= RECONCILE_TOLERANCE else "  ❌ 漏画了流向"))
        print("-" * 78)
        print("  资金流明细（null = 路径已知、数额待补，不是 0）：")
        for f in book.flows_of(node):
            # 走 book._num()：带引号的 "64e12" 是字符串，裸除会 TypeError。
            # 渲染路径和 validate 路径必须是同一套取值规则，否则"修好了金额"
            # 只是修好了其中一条路。
            amt = book._num(f.get("amount_cny"))
            other = f.get("to") if f.get("from") == node else f.get("from")
            arrow = "→" if f.get("from") == node else "←"
            print(f"    {arrow} {db._cell(other or '', 24)}"
                  f"{db._cell(f.get('kind', ''), 14)}"
                  f"{(f'{amt / 1e8:,.0f} 亿' if amt is not None else '待补'):>14}"
                  f"  {f.get('confidence', '-')}")
        return

    if getattr(args, "kinds", False):
        print("资金流类型（类型是聚合的唯一维度，别自由命名）：")
        for k, label in FLOW_KINDS.items():
            n = sum(1 for f in book.flows if f.get("kind") == k)
            print(f"  {db._cell(k, 16)}{db._cell(label, 40)}本账 {n} 条")
        return

    print(book.render_text())


def cmd_industry_check(args):
    """数据一致性自检：职业↔单元岗位 双向对齐

    退出码分三档，别把"还没干完的活"和"数据真的坏了"混成一个红灯：
      0  干净
      1  存在需要人工登记的真问题（悬空/重复/状态矛盾/对账漂移…）
      2  只剩「待建分区骨架没人认领」—— 声明要建的岗位还没有原子岗位对应。
         这是待建分区的补职业工作，不是数据坏了；但也不能算通过，所以单列一档。
    """
    db = _db(args)
    problems = db.validate()
    skeleton = [p for p in problems if "骨架悬空" in p]
    if not problems:
        # 条数读常量，不手抄：手抄的后果是 README / 文档 / 回执三个数互相打架
        print(f"✅ 分区/职业数据自检通过（{db.VALIDATE_CHECK_COUNT} 条校验）："
              f"{len(db.partitions)} 分区，{len(db.occupations)} 职业，"
              f"双向对齐无缺口")
        return
    other = [p for p in problems if "骨架悬空" not in p]
    if other:
        print(f"❌ 发现 {len(problems)} 处不一致（其中需人工登记的 {len(other)} 处）：")
        for p in problems:
            print("  - " + p)
        sys.exit(1)
    print(f"⚠️  {db.VALIDATE_CHECK_COUNT} 条校验：无数据错误，但 {len(skeleton)} 个待建分区的"
          f"岗位骨架还没有原子岗位认领（待建分区补职业，未完成）：")
    for p in skeleton:
        print("  - " + p)
    sys.exit(2)


# 导出：面向 CNB 制品库 / 知识库的扁平表
def cmd_industry_export(args):
    """导出扁平表到 out 目录（csv/json/sqlite），供制品库与知识库消费。

    - partitions.csv / occupations.csv：可直接进 CNB 制品库或喂知识库检索
    - industry.sqlite：单文件数据库（cnb 自带存储可放 data/ 制品里）
    """
    db = _db(args)
    out = getattr(args, "out", "out/industry-db")
    fmt = getattr(args, "format", "all")
    os.makedirs(out, exist_ok=True)
    snapshot = db.compute()
    written = []

    if fmt in ("all", "json"):
        path = os.path.join(out, "industry-db.json")
        occs = []
        for o in db.occupations:
            row = dict(o)
            row["access"] = db.access_of(o)   # 缺省 paid_direct 也显式给出
            if db.catalog is not None:
                gb = db.catalog.gb_code_of(o.get("id", ""))
                if gb:
                    row["gb_code"] = gb
                    row["gb_name"] = (db.catalog.entry(gb) or {}).get("name", "")
                    row["gb_path"] = db.catalog.path_of(gb)
            occs.append(row)
        # 两本账也进 JSON：可见度与资金流是"这份数据能答什么"的一部分，
        # 只导 partitions/occupations 的话，下游拿到的是一张没有缺口的漂亮表——
        # 而缺口本身就是要交付的信息。
        scales_json = []
        for p in db.partitions:
            pid = p.get("id", "")
            if not pid:
                continue
            scales_json.append({
                "partition": pid,
                "visibility": db.scales.visibility(pid),
                "metrics": {m: db.scales.metric(pid, m) for m in SCALE_METRICS},
            })
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"meta": {k: v for k, v in snapshot.items() if k != "rows"},
                       "partitions": snapshot["rows"],
                       "occupations": occs,
                       "scales": scales_json,
                       "money": {"summary": db.money.coverage_summary(),
                                 "nodes": db.money.nodes,
                                 "flows": db.money.flows,
                                 "leaks": db.money.leaks,
                                 "unobserved": db.money.unobserved}}, fh,
                      ensure_ascii=False, indent=2)
        written.append(path)

    if fmt in ("all", "csv"):
        ppath = os.path.join(out, "partitions.csv")
        with open(ppath, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["id", "name", "aliases", "status", "unit_id", "priority",
                        "member_count", "gdp_cny", "gdp_kind", "gdp_confidence",
                        "gdp_scope", "provider_ai",
                        "provider_hybrid", "provider_human", "provider_ai_declared",
                        "provider_hybrid_declared", "provider_human_declared",
                        "provider_ai_estimated", "provider_hybrid_estimated",
                        "provider_human_estimated",
                        "access_paid_direct", "access_non_market",
                        "access_org_internal", "access_household",
                        "employment_wan", "axes", "axis_edges", "demand_side",
                        "cluster_basis", "channels", "note"])
            for r in snapshot["rows"]:
                mix = r["provider_mix"] or {}
                dec = r.get("provider_mix_declared") or {}
                est = r.get("provider_mix_estimated") or {}
                w.writerow([r["id"], r["name"], "|".join(r["aliases"]), r["status"],
                            r["unit_id"], r["priority"], r["member_count"],
                            r["gdp_cny"] if r["gdp_cny"] is not None else "",
                            # 口径类型紧跟数字：只有 csv 里也带着，下游才不会把
                            # GMV 和增加值丢进同一个 sum()
                            r.get("gdp_kind", ""), r.get("gdp_confidence", ""),
                            r["gdp_scope"], mix.get("ai", ""), mix.get("hybrid", ""),
                            mix.get("human", ""),
                            dec.get("ai", ""), dec.get("hybrid", ""),
                            dec.get("human", ""),
                            # 估算列：无人味的实测是 0，唯一带人味的数在这里，
                            # 不给出口下游就只拿到一堆 0
                            est.get("ai", ""), est.get("hybrid", ""),
                            est.get("human", ""),
                            (r.get("access_mix") or {}).get("paid_direct", ""),
                            (r.get("access_mix") or {}).get("non_market", ""),
                            (r.get("access_mix") or {}).get("org_internal", ""),
                            (r.get("access_mix") or {}).get("household", ""),
                            (r.get("employment") if r.get("employment") is not None
                             else "-"),   # "-" = 无统计口径，与 0 区分
                            "|".join(r.get("axes", [])),
                            "|".join(f"{k}:{v}" for k, v in
                                     (r.get("axis_edges") or {}).items() if v),
                            "|".join(r["demand_side"]),
                            "|".join(r["cluster_basis"]),
                            "|".join(r["channels"]), r["note"]])
        written.append(ppath)

        opath = os.path.join(out, "occupations.csv")
        with open(opath, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["code", "id", "name", "views", "primary_view",
                        "deliverable", "provider", "billing", "access",
                        "baseline_occupation", "gb_code", "gb_name", "note"])
            for o in db.occupations:
                gb = db.catalog.gb_code_of(o.get("id", "")) if db.catalog else ""
                entry = db.catalog.entry(gb) if (db.catalog and gb) else None
                views = db.views_of_occupation(o.get("id", ""))
                primary = db.axis_view.primary_of(o.get("id", ""))
                w.writerow([
                    o.get("code", ""), o.get("id", ""), o.get("name", ""),
                    # 一个职业多行视角：用"分区:轴:权重"串起来，扁平表也能还原
                    "|".join(f"{m['partition']}:{m['axis']}:{m['weight']}"
                             for m in views),
                    primary[0]["partition"] if primary else "",
                    o.get("deliverable", ""), o.get("provider", ""),
                    o.get("billing", ""), db.access_of(o),
                    "1" if o.get("baseline_occupation") else "0",
                    gb, (entry or {}).get("name", ""), o.get("note", "")])
        written.append(opath)

        # 六口径规模账扁平表：一行一个（分区，口径），缺的口径也占一行。
        # 摊成宽表（每个口径一列）就退回"六个 NULL 分不清没登记还是没数"的老毛病。
        spath2 = os.path.join(out, "scales.csv")
        with open(spath2, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["partition", "metric", "value", "unit", "kind",
                        "basis", "source", "confidence", "missing_reason",
                        "visibility_level"])
            for p in db.partitions:
                pid = p.get("id", "")
                if not pid:
                    continue
                level = db.scales.visibility(pid)["level"]
                for m in SCALE_METRICS:
                    rec = db.scales.metric(pid, m)
                    if rec is None:
                        w.writerow([pid, m, "", "", "", "", "", "",
                                    db.scales.missing_reason(pid, m) or "", level])
                        continue
                    if m == "employment":
                        val, unit = rec.get("wan"), "wan"
                    elif m == "resource":
                        val, unit = rec.get("value"), rec.get("unit", "")
                    else:
                        val, unit = rec.get("cny"), "CNY"
                    w.writerow([pid, m, val, unit or "", rec.get("kind", "") or "",
                                rec.get("basis", "") or "", rec.get("source", "") or "",
                                rec.get("confidence", "") or "", "", level])
        written.append(spath2)

        # 资金流守恒账：三条扁平表（节点/边/差额）。下游能直接用 SQL 查
        # 「哪个节点的流入对不上」——这正是这套账存在的意义。
        npath = os.path.join(out, "money-nodes.csv")
        with open(npath, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["id", "type", "sector", "partition", "name",
                        "declared_in_cny", "declared_out_cny", "inflow_cny",
                        "outflow_cny", "net_cny", "unknown_edges", "in_gap_ratio",
                        "out_gap_ratio", "source"])
            recs = {(r["node"], r["side"]): r for r in db.money.reconcile()}
            for n in db.money.nodes:
                nid = n.get("id", "")
                pos = db.money.position(nid)
                w.writerow([nid, n.get("type", ""), n.get("sector", "") or "",
                            n.get("partition", "") or "", n.get("name", ""),
                            n.get("declared_in_cny", ""), n.get("declared_out_cny", ""),
                            pos["inflow"], pos["outflow"], pos["net"],
                            pos["unknown_edges"],
                            (recs.get((nid, "in")) or {}).get("gap_ratio", ""),
                            (recs.get((nid, "out")) or {}).get("gap_ratio", ""),
                            n.get("source", "") or ""])
        written.append(npath)

        fpath = os.path.join(out, "money-flows.csv")
        with open(fpath, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["from", "to", "kind", "kind_label", "amount_cny",
                        "confidence", "basis"])
            for f in db.money.flows:
                w.writerow([f.get("from", ""), f.get("to", ""), f.get("kind", ""),
                            FLOW_KINDS.get(f.get("kind", ""), ""),
                            f.get("amount_cny") if f.get("amount_cny") is not None else "",
                            f.get("confidence", "") or "", f.get("basis", "") or ""])
        written.append(fpath)

    if fmt in ("all", "sqlite"):
        import sqlite3
        spath = os.path.join(out, "industry.sqlite")
        if os.path.exists(spath):
            os.remove(spath)
        conn = sqlite3.connect(spath)
        # 建表语句从单源渲染，不再手写在 CLI 里：手写那版只有 SQLite 方言、
        # 列顺序靠 tuple 位置对齐，加一列要同时改三处，漏一处就静默错位。
        conn.executescript(industry_schema.ddl("sqlite"))
        rows = industry_schema.rows_of(db, snapshot)
        for table in industry_schema.TABLES:      # 按定义顺序插入，外键不悬空
            cols = industry_schema.columns_of(table["name"])
            sql = (f'INSERT INTO "{table["name"]}" ('
                   + ", ".join(f'"{c}"' for c in cols) + ") VALUES ("
                   + ", ".join("?" * len(cols)) + ")")
            conn.executemany(sql, rows[table["name"]])
        conn.commit()
        conn.close()
        written.append(spath)

        # 双方言 DDL + 与方言无关的数据 SQL：买服务器时把这三份丢进去就能建库，
        # 不需要跑 Python，也不需要人工把 SQLite 语法改写成 PG。
        for name, content in (
                ("00-schema.sqlite.sql", industry_schema.ddl("sqlite")),
                ("00-schema.postgresql.sql", industry_schema.ddl("postgresql")),
                ("10-data.sql", industry_schema.data_sql(db, snapshot))):
            path = os.path.join(out, name)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)
            written.append(path)

    print(f"已导出 {len(written)} 个文件到 {out}/ :")
    for p in written:
        print("  - " + p)


# ---- 全球分类框架（四根轴：职业 / 行业 / 税收 / 产出）----
def cmd_reference_isco(args):
    """查 ISCO-08 参考表：按编码看归属链路，或按名称/示例职位名检索。

    ISCO-08 是各国职业分类的公共母版（SOC/ANZSCO/NOC/KldB/中国大典都按它对标），
    用来回答"这个工种在英文里叫什么、国际口径归哪一类"。
    它不参与 coverage 分母：436 个细类包住全球全行业，拿它当分母只会稀释覆盖率。
    """
    from hanghang.engine.global_framework import IscoCatalog, LEVEL_NAMES

    cat = IscoCatalog()
    if not cat.by_level[4] and not cat.by_level[1]:
        print(f"未加载 ISCO-08 参考表: {cat.path}")
        sys.exit(1)

    code = getattr(args, "code", "") or ""
    kw = getattr(args, "search", "") or ""
    limit = getattr(args, "limit", 20) or 0

    if code:
        e = cat.entry(code)
        if not e:
            print(f"未找到 ISCO-08 编码: {code}")
            sys.exit(1)
        lvl = cat.level_of(code)
        print(f"■ {code} {e.get('name')}  [{LEVEL_NAMES.get(lvl, '?')}]")
        print(f"  归属: {cat.path_of(code)}")
        print(f"  技能等级: {e.get('skill_level')}")
        kids = cat.children_of(code)
        if kids:
            print(f"  下级({len(kids)}):")
            for k in kids:
                print(f"    - {k.get('code')} {k.get('name')}")
        ex = e.get("examples") or []
        if ex:
            print(f"  官方示例职位({len(ex)}): " + "、".join(ex))
        if e.get("description"):
            print(f"  描述: {e['description']}")
        return

    if kw:
        hits = cat.search(kw, limit=limit)
        if not hits:
            print(f"ISCO-08 里没有名称或示例职位名含「{kw}」的条目")
            return
        print(f"{'编码':<8}{'名称':<44}示例职位")
        for e in hits:
            ex = "、".join((e.get("examples") or [])[:3])
            print(f"{e.get('code', ''):<8}{e.get('name', '')[:42]:<44}{ex}")
        print(f"\n命中 {len(hits)} 条（--limit 0 看全部）")
        return

    s = cat.stats
    print(f"ISCO-08 参考表（{cat.version}）")
    print(f"  大类 {s.get('major_groups', 0)} / 次大类 {s.get('sub_major_groups', 0)}"
          f" / 小类 {s.get('minor_groups', 0)} / 细类 {s.get('unit_groups', 0)}"
          f" · 官方示例职位 {cat.example_count()} 条")
    print("  口径提醒: 436 个细类包住全球全行业，是本表全集，不是待办清单")
    for k in cat.by_level[1]:
        n = len(cat.children_of(k.get("code", "")))
        print(f"  - {k.get('code')} {k.get('name')}（次大类 {n}）")


def cmd_reference_sources(args):
    """分类体系索引：四根轴各自有哪些权威标准、已接入还是待接。"""
    from hanghang.engine.global_framework import ClassificationSources

    src = ClassificationSources()
    if not src.sources:
        print(f"未加载分类体系索引: {src.path}")
        sys.exit(1)
    problems = src.validate()
    print(src.render_text(axis=getattr(args, "axis", "") or ""))
    if problems:
        print(f"\n⚠️ 索引自检发现 {len(problems)} 处问题：")
        for p in problems:
            print("  - " + p)
