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
    if members:
        print(f"  成员职业({len(members)}):")
        for o in members:
            flag = "基线" if o.get("baseline_occupation") else "扩展"
            print(f"    - {o.get('id'):<24}{o.get('name'):<14}"
                  f"{o.get('provider', '-'):<8}{o.get('billing', '-'):<14}{flag}")
    else:
        print("  成员职业: 未登记（该分区尚无职业入库，属覆盖缺口）")


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
              f"（这是候选池，不是待办：军队人员/采矿工种本就不该建数字员工单元）")
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
                        "demand_side", "cluster_basis", "channels", "note"])
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
                            "|".join(r["demand_side"]),
                            "|".join(r["cluster_basis"]),
                            "|".join(r["channels"]), r["note"]])
        written.append(ppath)

        opath = os.path.join(out, "occupations.csv")
        with open(opath, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["id", "name", "partition_id", "unit_role", "deliverable",
                        "provider", "billing", "baseline_occupation", "gb_code",
                        "gb_name", "note"])
            for o in db.occupations:
                gb = db.catalog.gb_code_of(o.get("id", "")) if db.catalog else ""
                entry = db.catalog.entry(gb) if (db.catalog and gb) else None
                w.writerow([o.get("id", ""), o.get("name", ""),
                            o.get("unit_id", ""), o.get("unit_role", ""),
                            o.get("deliverable", ""), o.get("provider", ""),
                            o.get("billing", ""),
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
            demand_side TEXT, cluster_basis TEXT, channels TEXT, note TEXT)""")
        conn.execute("""CREATE TABLE occupation(
            id TEXT PRIMARY KEY, name TEXT, partition_id TEXT, unit_role TEXT,
            deliverable TEXT, provider TEXT, billing TEXT,
            baseline INTEGER, gb_code TEXT, gb_name TEXT, note TEXT)""")
        for r in snapshot["rows"]:
            mix = r["provider_mix"] or {}
            dec = r.get("provider_mix_declared") or {}
            conn.execute("INSERT INTO partition VALUES "
                         "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (r["id"], r["name"], "|".join(r["aliases"]), r["status"],
                          r["unit_id"], r["priority"], r["gdp_cny"], r["gdp_scope"],
                          r["gdp_source"], mix.get("ai"), mix.get("hybrid"),
                          mix.get("human"), dec.get("ai"), dec.get("hybrid"),
                          dec.get("human"), "|".join(r["demand_side"]),
                          "|".join(r["cluster_basis"]), "|".join(r["channels"]),
                          r["note"]))
        for o in db.occupations:
            gb = db.catalog.gb_code_of(o.get("id", "")) if db.catalog else ""
            entry = db.catalog.entry(gb) if (db.catalog and gb) else None
            conn.execute("INSERT INTO occupation VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         (o.get("id", ""), o.get("name", ""), o.get("unit_id", ""),
                          o.get("unit_role", ""), o.get("deliverable", ""),
                          o.get("provider", ""), o.get("billing", ""),
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
