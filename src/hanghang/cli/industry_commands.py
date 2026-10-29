"""industry-db 命令：行业分区定义库查询 / 自检 / 导出。"""
from __future__ import annotations

import csv
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from hanghang.engine.industry_db import IndustryDatabase


def _db(args):
    data_dir = getattr(args, "data_dir", "") or None
    return IndustryDatabase(data_dir=data_dir)


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
    print(f"  年产值: {f'{gdp / 1e8:,.0f} 亿元' if gdp else '无市场口径(刻意留空)'}")
    if p.get("gdp_scope"):
        print(f"  产值口径: {p['gdp_scope']}")
    if p.get("gdp_source"):
        print(f"  来源: {p['gdp_source']}")
    print(f"  单元: {p.get('unit_id') or '未建'}")
    if p.get("channels"):
        print("  数据渠道: " + "、".join(p["channels"]))
    if p.get("note"):
        print(f"  备注: {p['note']}")
    planned = p.get("planned_roles", []) or []
    if planned and not p.get("unit_id"):
        # 骨架里存的是 unit_role（岗位名），直接打印等于给内部命名；
        # 能反查到职业就带中文名，反查不到原样给出，方便对齐
        named = []
        for role in planned:
            hit = next((o for o in db.occupations
                        if o.get("unit_id") == p.get("id")
                        and (o.get("unit_role") or "") == role), None)
            named.append(f"{role}({hit.get('name')})" if hit else role)
        print("  计划岗位(骨架): " + "、".join(named))
    if members:
        print(f"  成员职业({len(members)}):")
        for o in members:
            flag = "基线" if o.get("baseline_occupation") else "扩展"
            print("    - " + db._pad(o.get("id", ""), 26)
                  + db._pad(o.get("name", ""), 20)
                  + db._pad(o.get("provider", "-"), 8)
                  + db._pad(o.get("billing", "-"), 14) + flag)
    else:
        print("  成员职业: 未登记（该分区尚无职业入库，属覆盖缺口）")


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
            gdp = f"{r['gdp_cny'] / 1e8:,.0f}亿" if r.get("gdp_cny") else "无口径"
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
    print(f"{'职业':<16}{'名称':<14}{'分区':<18}{'通道':<14}计费")
    for o in rows:
        print(f"{o.get('id', ''):<16}{o.get('name', '')[:12]:<14}"
              f"{o.get('unit_id') or '-':<18}{db.access_of(o):<14}"
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
    """列出职业（可按分区/提供者/收费方式过滤）"""
    db = _db(args)
    rows = db.occupations
    if getattr(args, "partition", ""):
        rows = [o for o in rows if o.get("unit_id") == args.partition]
    if getattr(args, "provider", ""):
        rows = [o for o in rows if o.get("provider") == args.provider]
    if getattr(args, "billing", ""):
        rows = [o for o in rows if o.get("billing") == args.billing]
    if getattr(args, "access", ""):
        rows = [o for o in rows if db.access_of(o) == args.access]
    if getattr(args, "unassigned", False):
        rows = [o for o in rows if not o.get("unit_id")]
    if not rows:
        print("无匹配职业")
        return
    print(f"{'职业ID':<26}{'名称':<14}{'分区':<16}{'交付物':<8}{'提供者':<8}"
          f"{'收费':<12}{'大典编码':<13}基线")
    for o in rows:
        part = o.get("unit_id") or "-"
        gb = db.catalog.gb_code_of(o.get("id", "")) if db.catalog else ""
        print(f"{o.get('id', ''):<26}{o.get('name', ''):<14}{part:<16}"
              f"{o.get('deliverable', '-'):<8}{o.get('provider', '-'):<8}"
              f"{o.get('billing', '-'):<12}{gb or '-':<13}"
              f"{'是' if o.get('baseline_occupation') else '否'}")
    mapped = sum(1 for o in rows
                 if db.catalog and db.catalog.gb_code_of(o.get("id", "")))
    print(f"\n合计 {len(rows)} 个职业"
          + (f"，其中 {mapped} 个已挂大典编码" if db.catalog else ""))


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
                      f"  [{o.get('unit_id') or '未挂分区'}]")
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


def cmd_industry_check(args):
    """数据一致性自检：职业↔单元岗位 双向对齐"""
    db = _db(args)
    problems = db.validate()
    if not problems:
        print(f"✅ 分区/职业数据自检通过：{len(db.partitions)} 分区，"
              f"{len(db.occupations)} 职业，双向对齐无缺口")
        return
    print(f"❌ 发现 {len(problems)} 处不一致：")
    for p in problems:
        print("  - " + p)
    sys.exit(1)


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
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"meta": {k: v for k, v in snapshot.items() if k != "rows"},
                       "partitions": snapshot["rows"],
                       "occupations": occs}, fh,
                      ensure_ascii=False, indent=2)
        written.append(path)

    if fmt in ("all", "csv"):
        ppath = os.path.join(out, "partitions.csv")
        with open(ppath, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["id", "name", "aliases", "status", "unit_id", "priority",
                        "member_count", "gdp_cny", "gdp_scope", "provider_ai",
                        "provider_hybrid", "provider_human", "provider_ai_declared",
                        "provider_hybrid_declared", "provider_human_declared",
                        "access_paid_direct", "access_non_market",
                        "access_org_internal", "access_household",
                        "employment_wan", "axes", "demand_side", "cluster_basis",
                        "channels", "note"])
            for r in snapshot["rows"]:
                mix = r["provider_mix"] or {}
                dec = r.get("provider_mix_declared") or {}
                w.writerow([r["id"], r["name"], "|".join(r["aliases"]), r["status"],
                            r["unit_id"], r["priority"], r["member_count"],
                            r["gdp_cny"] if r["gdp_cny"] is not None else "",
                            r["gdp_scope"], mix.get("ai", ""), mix.get("hybrid", ""),
                            mix.get("human", ""),
                            dec.get("ai", ""), dec.get("hybrid", ""),
                            dec.get("human", ""),
                            (r.get("access_mix") or {}).get("paid_direct", ""),
                            (r.get("access_mix") or {}).get("non_market", ""),
                            (r.get("access_mix") or {}).get("org_internal", ""),
                            (r.get("access_mix") or {}).get("household", ""),
                            (r.get("employment") if r.get("employment") is not None
                             else "-"),   # "-" = 无统计口径，与 0 区分
                            "|".join(r.get("axes", [])),
                            "|".join(r["demand_side"]),
                            "|".join(r["cluster_basis"]),
                            "|".join(r["channels"]), r["note"]])
        written.append(ppath)

        opath = os.path.join(out, "occupations.csv")
        with open(opath, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["id", "name", "partition_id", "unit_role", "deliverable",
                        "provider", "billing", "access", "baseline_occupation",
                        "gb_code", "gb_name", "note"])
            for o in db.occupations:
                gb = db.catalog.gb_code_of(o.get("id", "")) if db.catalog else ""
                entry = db.catalog.entry(gb) if (db.catalog and gb) else None
                w.writerow([o.get("id", ""), o.get("name", ""),
                            o.get("unit_id", ""), o.get("unit_role", ""),
                            o.get("deliverable", ""), o.get("provider", ""),
                            o.get("billing", ""), db.access_of(o),
                            "1" if o.get("baseline_occupation") else "0",
                            gb, (entry or {}).get("name", ""), o.get("note", "")])
        written.append(opath)

    if fmt in ("all", "sqlite"):
        import sqlite3
        spath = os.path.join(out, "industry.sqlite")
        if os.path.exists(spath):
            os.remove(spath)
        conn = sqlite3.connect(spath)
        conn.execute("""CREATE TABLE partition(
            id TEXT PRIMARY KEY, name TEXT, aliases TEXT, status TEXT,
            unit_id TEXT, priority TEXT, gdp_cny INTEGER, gdp_scope TEXT,
            gdp_source TEXT, provider_ai REAL, provider_hybrid REAL,
            provider_human REAL, provider_ai_declared REAL,
            provider_hybrid_declared REAL, provider_human_declared REAL,
            access_paid_direct REAL, access_non_market REAL,
            access_org_internal REAL, access_household REAL,
            employment_wan REAL, axes TEXT,
            demand_side TEXT, cluster_basis TEXT, channels TEXT, note TEXT)""")
        conn.execute("""CREATE TABLE occupation(
            id TEXT PRIMARY KEY, name TEXT, partition_id TEXT, unit_role TEXT,
            deliverable TEXT, provider TEXT, billing TEXT, access TEXT,
            baseline INTEGER, gb_code TEXT, gb_name TEXT, note TEXT)""")
        for r in snapshot["rows"]:
            mix = r["provider_mix"] or {}
            dec = r.get("provider_mix_declared") or {}
            acc = r.get("access_mix") or {}
            conn.execute(
                f"INSERT INTO partition VALUES ({','.join('?' * 25)})",
                (r["id"], r["name"], "|".join(r["aliases"]), r["status"],
                 r["unit_id"], r["priority"], r["gdp_cny"], r["gdp_scope"],
                 r["gdp_source"], mix.get("ai"), mix.get("hybrid"),
                 mix.get("human"), dec.get("ai"), dec.get("hybrid"),
                 dec.get("human"), acc.get("paid_direct"), acc.get("non_market"),
                 acc.get("org_internal"), acc.get("household"),
                 r.get("employment"), "|".join(r.get("axes", [])),
                 "|".join(r["demand_side"]),
                 "|".join(r["cluster_basis"]), "|".join(r["channels"]),
                 r["note"]))
        for o in db.occupations:
            gb = db.catalog.gb_code_of(o.get("id", "")) if db.catalog else ""
            entry = db.catalog.entry(gb) if (db.catalog and gb) else None
            conn.execute(
                f"INSERT INTO occupation VALUES ({','.join('?' * 12)})",
                (o.get("id", ""), o.get("name", ""), o.get("unit_id", ""),
                 o.get("unit_role", ""), o.get("deliverable", ""),
                 o.get("provider", ""), o.get("billing", ""), db.access_of(o),
                 1 if o.get("baseline_occupation") else 0,
                 gb, (entry or {}).get("name", ""), o.get("note", "")))
        # 大典参考表整表导出：补全缺口时不必再去找原始 PDF
        if db.catalog is not None:
            conn.execute("""CREATE TABLE gb_catalog(
                code TEXT PRIMARY KEY, name TEXT, gbm TEXT, major TEXT,
                middle TEXT, minor TEXT, marks TEXT, path TEXT, desc TEXT)""")
            for e in db.catalog.occupations:
                conn.execute("INSERT INTO gb_catalog VALUES (?,?,?,?,?,?,?,?,?)",
                             (e.get("code", ""), e.get("name", ""), e.get("gbm", ""),
                              e.get("major", ""), e.get("middle", ""),
                              e.get("minor", ""), "|".join(e.get("marks") or []),
                              db.catalog.path_of(e.get("code", "")),
                              e.get("desc", "")))
        conn.commit()
        conn.close()
        written.append(spath)

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
