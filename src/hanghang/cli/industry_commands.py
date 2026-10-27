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
    mix = p.get("provider_mix") or {}
    print(f"  供给结构: AI {mix.get('ai', '-')}% / 混合 {mix.get('hybrid', '-')}%"
          f" / 纯人 {mix.get('human', '-')}%")
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
    members = db.members_of(p.get("id", ""))
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
    print(f"{'职业ID':<26}{'名称':<14}{'分区':<16}{'交付物':<8}{'提供者':<8}{'收费':<12}基线")
    for o in rows:
        part = o.get("unit_id") or "-"
        print(f"{o.get('id', ''):<26}{o.get('name', ''):<14}{part:<16}"
              f"{o.get('deliverable', '-'):<8}{o.get('provider', '-'):<8}"
              f"{o.get('billing', '-'):<12}"
              f"{'是' if o.get('baseline_occupation') else '否'}")
    print(f"\n合计 {len(rows)} 个职业")


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
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"meta": {k: v for k, v in snapshot.items() if k != "rows"},
                       "partitions": snapshot["rows"],
                       "occupations": db.occupations}, fh,
                      ensure_ascii=False, indent=2)
        written.append(path)

    if fmt in ("all", "csv"):
        ppath = os.path.join(out, "partitions.csv")
        with open(ppath, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["id", "name", "aliases", "status", "unit_id", "priority",
                        "member_count", "gdp_cny", "gdp_scope", "provider_ai",
                        "provider_hybrid", "provider_human", "demand_side",
                        "cluster_basis", "channels", "note"])
            for r in snapshot["rows"]:
                mix = r["provider_mix"] or {}
                w.writerow([r["id"], r["name"], "|".join(r["aliases"]), r["status"],
                            r["unit_id"], r["priority"], r["member_count"],
                            r["gdp_cny"] if r["gdp_cny"] is not None else "",
                            r["gdp_scope"], mix.get("ai", ""), mix.get("hybrid", ""),
                            mix.get("human", ""), "|".join(r["demand_side"]),
                            "|".join(r["cluster_basis"]),
                            "|".join(r["channels"]), r["note"]])
        written.append(ppath)

        opath = os.path.join(out, "occupations.csv")
        with open(opath, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["id", "name", "partition_id", "unit_role", "deliverable",
                        "provider", "billing", "baseline_occupation", "note"])
            for o in db.occupations:
                w.writerow([o.get("id", ""), o.get("name", ""),
                            o.get("unit_id", ""), o.get("unit_role", ""),
                            o.get("deliverable", ""), o.get("provider", ""),
                            o.get("billing", ""),
                            "1" if o.get("baseline_occupation") else "0",
                            o.get("note", "")])
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
            gdp_source TEXT, provider_ai INTEGER, provider_hybrid INTEGER,
            provider_human INTEGER, demand_side TEXT, cluster_basis TEXT,
            channels TEXT, note TEXT)""")
        conn.execute("""CREATE TABLE occupation(
            id TEXT PRIMARY KEY, name TEXT, partition_id TEXT, unit_role TEXT,
            deliverable TEXT, provider TEXT, billing TEXT,
            baseline INTEGER, note TEXT)""")
        for r in snapshot["rows"]:
            mix = r["provider_mix"] or {}
            conn.execute("INSERT INTO partition VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (r["id"], r["name"], "|".join(r["aliases"]), r["status"],
                          r["unit_id"], r["priority"], r["gdp_cny"], r["gdp_scope"],
                          r["gdp_source"], mix.get("ai"), mix.get("hybrid"),
                          mix.get("human"), "|".join(r["demand_side"]),
                          "|".join(r["cluster_basis"]), "|".join(r["channels"]),
                          r["note"]))
        for o in db.occupations:
            conn.execute("INSERT INTO occupation VALUES (?,?,?,?,?,?,?,?,?)",
                         (o.get("id", ""), o.get("name", ""), o.get("unit_id", ""),
                          o.get("unit_role", ""), o.get("deliverable", ""),
                          o.get("provider", ""), o.get("billing", ""),
                          1 if o.get("baseline_occupation") else 0, o.get("note", "")))
        conn.commit()
        conn.close()
        written.append(spath)

    print(f"已导出 {len(written)} 个文件到 {out}/ :")
    for p in written:
        print("  - " + p)
