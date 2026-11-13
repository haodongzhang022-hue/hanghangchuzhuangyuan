"""岗位 / 行业类 / 利益链条的**实库**（SQLite，零运维、可当场用）

前面的 ``schema_sql`` 只产出 DDL 文本 —— 那是图纸，不是房子。这个模块建的是房子：

    build(db_path)   画像卡 + 词表 → 一份能开的 SQLite 库（幂等重建）
    read(db_path)    从库里读回，渲染成与 ``RoleCardStore`` 同构的岗位卡

为什么是 SQLite：不依赖服务、不落凭据、文件即库，能直接进仓库被随身带走；
将来接服务器（PostgreSQL / 云仓）时表名列名一致，只换连接与方言 ——
``schema_sql.ddl("postgresql")`` 就是那份结构，不需要重写数据模型。

刻意不做的事：
  · 不建公司名录表。企业名录住 CRM / ATS / 企业名录，库里只存检索方式。
  · 不把列表型字段塞成 JSON 一列。交付物/KPI/上下游一条一行，才能按值查、能统计。
  · 不在库里做视图/触发器/存储过程。跨库麻烦，逻辑留在 Python。
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from typing import Dict, List, Optional

from . import chain as chain_mod
from .chain import CHAIN_FIELDS
from . import schema_sql
from .models import (
    CapabilityProfile, ReadinessReport, RoleCard, RoleProfile, StakeholderChain,
)

GENERATOR = "scripts/build_role_db.py"
DEFAULT_DB_PATH = os.path.join("data", "db", "hanghang.db")

# 六维里需要落 role_profile_item 的清单型字段
_ITEM_FIELDS = (
    ("analysis", "deliverables"),
    ("analysis", "inputs"),
    ("analysis", "outputs"),
    ("analysis", "kpis"),
    ("persona", "decision_rights"),
    ("persona", "constraints"),
    ("plugin", "tools"),
    ("plugin", "mcp_categories"),
    ("stakeholders", "beneficiaries"),
    ("stakeholders", "blockers"),
    ("stakeholders", "incentives"),
    ("stakeholders", "risk_notes"),
    ("capability", "core"),
    ("capability", "tools"),
    ("capability", "knowledge"),
    ("capability", "soft"),
)


def _text(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def _float(value) -> Optional[float]:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def _list(value) -> List[str]:
    if not value:
        return []
    return [str(v) for v in (value if isinstance(value, (list, tuple)) else [value])]


def _index_snapshot(entry) -> Optional[str]:
    """类目索引快照：``来源|查询式1;查询式2``。库里能直接看出"去哪个系统怎么查"。"""
    idx = entry.index or {}
    if not idx:
        return None
    return f"{idx.get('source') or ''}|{';'.join(idx.get('query') or [])}"


def _chain_refs(store) -> List[tuple]:
    """链上每一处引用（已归一）：类目 / 接口 / 岗位三类落点都记下来。

    旧版只落类目：一处引用如果归一成了「岗位」，就会被静默丢掉 —— 库里看不出
    「架构师的下游是 developer」。现在三类都落，``ref_kind`` 区分，反查才完整。
    """
    rows = []
    for uid, roles in sorted(store.profiles.items()):
        for rname, profile in sorted(roles.items()):
            entries = store.classes.normalize_chain(
                {f: list(getattr(profile.stakeholders, f) or []) for f in CHAIN_FIELDS}, uid)
            for field, items in entries.items():
                for e in items:
                    if e.kind == chain_mod.KIND_ROLE:
                        target, ref_unit = e.value, e.unit or ""
                    else:
                        target, ref_unit = e.value, ""
                    rows.append((uid, rname, field, e.raw, target, e.kind, ref_unit,
                                 e.ref or None, _index_snapshot(e), e.note or None))
    return rows


# --------------------------------------------------------------------------- 写
def _insert_classes(conn: sqlite3.Connection, store) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    classes = store.classes

    rows = schema_sql.entity_rows(classes)
    conn.executemany(
        "INSERT INTO industry_class (name, kind, label, is_entity, source_file)"
        " VALUES (?, ?, ?, ?, ?)", rows)
    counts["industry_class"] = len(rows)

    alias_rows = []
    for canon, names in sorted(classes.aliases.items()):
        # 单元的中文名走 unit_alias（中文行业名 → unit_id），不参与类目别名，
        # 否则会往 class_alias 里塞一个没有对应 industry_class 的名字。
        if canon not in classes.classes:
            continue
        src = classes.sources.get(canon, "")
        for alias in (names if isinstance(names, list) else [names]):
            alias_rows.append((canon, str(alias), src))
    conn.executemany(
        "INSERT INTO class_alias (class_name, alias, source_file) VALUES (?, ?, ?)", alias_rows)
    counts["class_alias"] = len(alias_rows)

    idx_rows = []
    for name, spec in sorted(classes.classes.items()):
        idx = (spec or {}).get("index")
        if not isinstance(idx, dict):
            continue
        for expr in (idx.get("query") or []):
            idx_rows.append((name, str(idx.get("source") or ""), str(expr)))
    conn.executemany(
        "INSERT INTO class_index_src (class_name, source, query_expr) VALUES (?, ?, ?)", idx_rows)
    counts["class_index_src"] = len(idx_rows)

    ref_rows = []
    for item in _chain_refs(store):
        ref_rows.append(item)
    conn.executemany(
        "INSERT INTO role_chain_ref (unit_id, role_name, field, raw_value, class_name,"
        " ref_kind, ref_unit, ref, ref_index, ref_note)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", ref_rows)
    counts["role_chain_ref"] = len(ref_rows)
    return counts


def _insert_cards(conn: sqlite3.Connection, cards: List[RoleCard], when: str) -> Dict[str, int]:
    counts = {k: 0 for k in ("industry_unit", "industry_role", "role_profile",
                             "role_profile_item", "capability_score", "workflow",
                             "workflow_step", "step_assertion", "plugin_artifact",
                             "readiness")}
    seen_units = set()
    seen_roles = set()
    unit_meta: Dict[str, tuple] = {}

    for card in cards:
        uid, rname = card.unit_id, card.role
        if uid not in seen_units:
            seen_units.add(uid)
            unit = store_unit(card)
            unit_meta[uid] = (uid, unit["industry"], ",".join(unit["alias"]),
                              unit["version"], card.sources[0] if card.sources else "")
            conn.execute("INSERT INTO industry_unit (unit_id, industry, industry_alias,"
                         " version, source_file) VALUES (?, ?, ?, ?, ?)", unit_meta[uid])
            counts["industry_unit"] += 1
        if (uid, rname) not in seen_roles:
            seen_roles.add((uid, rname))
            conn.execute(
                "INSERT INTO industry_role (unit_id, role_name, prefix, description, keywords)"
                " VALUES (?, ?, ?, ?, ?)",
                (uid, rname, card.prefix, card.description, ",".join(card.keywords)))
            counts["industry_role"] += 1

        p = card.profile
        # 没画像的岗位（如注册表有、画像还没写的）不落 role_profile 行：
        # 「缺行」才是准确的表达。落一行全空的会读回成"有画像但六维全空"，
        # 与内存里的 None 对不上，--check 会误报，调用方也分不清「没写」和「写了空」。
        if p is not None:
            cap = card.capability()
            scoring = {k: v for k, v in (cap.scoring or {}).items()}
            conn.execute(
                "INSERT INTO role_profile (unit_id, role_name, mission, seniority, mindset, tone,"
                " bundle, install_hint, scoring_avg, source_file)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (uid, rname,
                 _text((p.analysis or {}).get("mission")),
                 _text((p.persona or {}).get("seniority")),
                 _text((p.persona or {}).get("mindset")),
                 _text((p.persona or {}).get("tone")),
                 _text((p.plugin or {}).get("bundle")),
                 _text((p.plugin or {}).get("install_hint")),
                 _text(cap.average_score()) if scoring else None,
                 p.source or ""))
            counts["role_profile"] += 1

            items = []
            for dim, field in _ITEM_FIELDS:
                holder = getattr(p, dim, None)
                if holder is None:          # stakeholders / capability 是 dataclass，不是 dict
                    continue
                values = (getattr(holder, field, None) if not isinstance(holder, dict)
                          else holder.get(field))
                for pos, val in enumerate(_list(values), 1):
                    items.append((uid, rname, dim, field, str(val), pos))
            conn.executemany(
                "INSERT INTO role_profile_item (unit_id, role_name, dimension, field, value,"
                " position) VALUES (?, ?, ?, ?, ?, ?)", items)
            counts["role_profile_item"] += len(items)

            scores = [(uid, rname, str(k), _text(v)) for k, v in sorted(scoring.items())]
            conn.executemany(
                "INSERT INTO capability_score (unit_id, role_name, dimension, score)"
                " VALUES (?, ?, ?, ?)", scores)
            counts["capability_score"] += len(scores)

        for wf_pos, wf in enumerate(card.workflows, 1):
            cur = conn.execute(
                "INSERT INTO workflow (unit_id, role_name, wf_id, name, template, trigger,"
                " handoff_out, is_default, activation_weight, position)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (uid, rname, str(wf.get("id", "")), _text(wf.get("name")),
                 _text(wf.get("template")), _text(wf.get("trigger")),
                 _text(wf.get("handoff_out")),
                 1 if wf.get("default") else 0,
                 _text((card.activation or {}).get("weight")), wf_pos))
            wf_row_id = cur.lastrowid
            counts["workflow"] += 1
            for st_pos, step in enumerate(wf.get("steps") or [], 1):
                sid = str(step.get("id", ""))
                conn.execute(
                    "INSERT INTO workflow_step (workflow_id, step_id, name, agent_role,"
                    " playbook, runtime, position) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (wf_row_id, sid, _text(step.get("name")), _text(step.get("agent_role")),
                     _text(step.get("playbook")), _text(step.get("runtime")) or "agent", st_pos))
                counts["workflow_step"] += 1
                asserts = [(wf_row_id, sid, kind, str(v), pos)
                           for kind in ("preconditions", "outputs", "verify")
                           for pos, v in enumerate(_list(step.get(kind)), 1)]
                conn.executemany(
                    "INSERT INTO step_assertion (workflow_id, step_id, kind, value, position)"
                    " VALUES (?, ?, ?, ?, ?)", asserts)
                counts["step_assertion"] += len(asserts)

        # 技能包挂岗位，不挂工序：放进 workflow 的循环里，没写工序的岗位
        # （还没接默认模板）会连技能包一起静默丢掉。
        arts = [(uid, rname, str(a.get("name") or ""), _text(a.get("kind")),
                 _text(a.get("path")), _text(a.get("upstream")), pos)
                for pos, a in enumerate(card.plugin_artifacts, 1)]
        conn.executemany(
            "INSERT INTO plugin_artifact (unit_id, role_name, name, kind, path, upstream,"
            " position) VALUES (?, ?, ?, ?, ?, ?, ?)", arts)
        counts["plugin_artifact"] += len(arts)

        # readiness 独立于画像：没写画像的岗位同样有就绪度（D 级 + 缺口清单），
        # 它不挂在 role_profile 的外键上，所以放在 if 之外。
        r = card.readiness
        conn.execute(
            "INSERT INTO readiness (unit_id, role_name, score, grade, label, factor, gaps)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (uid, rname, _text(r.score if r else 0), r.grade if r else None,
             r.label if r else None,
             ";".join(f"{k}={v}" for k, v in (r.factors or {}).items()) if r else None,
             "；".join(r.gaps or []) if r else None))
        counts["readiness"] += 1
    return counts


def store_unit(card: RoleCard) -> dict:
    """单元元信息（行业名/别名/版本）—— 由注册表给出，库里落一份便于 join。"""
    unit = getattr(card, "_unit", None)
    if unit is None:
        return {"industry": card.industry, "alias": [], "version": ""}
    return {
        "industry": getattr(unit, "industry", card.industry) or card.industry,
        "alias": list(getattr(unit, "industry_alias", []) or []),
        "version": str(getattr(unit, "version", "") or ""),
    }


def build(store, db_path: str = DEFAULT_DB_PATH, when: Optional[str] = None) -> dict:
    """把画像卡 + 词表落成一份 SQLite 库（文件先删后建，保证幂等）。

    返回每张表的行数，供 CLI / CI 打点。**不写公司名录**，也不写任何凭据。
    """
    when = when or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cards = store.all_cards()

    # 给每张卡挂上单元对象（取行业名/别名/版本用，避免再查一遍注册表）
    for card in cards:
        setattr(card, "_unit", store.registry.get_unit(card.unit_id))

    parent = os.path.dirname(os.path.abspath(db_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(schema_sql.ddl("sqlite"))
        counts = {"schema_version": 1}
        conn.execute(
            "INSERT INTO schema_version (version, built_at, source, generator)"
            " VALUES (?, ?, ?, ?)",
            (schema_sql.SCHEMA_VERSION, when, "data/ (role-profiles + industry-classes)", GENERATOR))
        counts.update(_insert_classes(conn, store))
        counts.update(_insert_cards(conn, cards, when))
        conn.commit()

        # 定义文件随库走：拿到 .db 的人先读到口径，再读表
        _write_definition(conn)
        conn.commit()
    finally:
        conn.close()
    return counts


def _write_definition(conn: sqlite3.Connection) -> None:
    """库里带一份结构自述（表名→列名逐行），换库时对得上，也免得人手抄。"""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_definition ("
        " table_name TEXT NOT NULL, position INTEGER NOT NULL,"
        " column_name TEXT NOT NULL, type TEXT NOT NULL,"
        " PRIMARY KEY (table_name, position))")
    rows = []
    for table in schema_sql._TABLES:      # noqa: SLF001 同包内读取单源定义
        for pos, (name, typ, notnull) in enumerate(table["columns"], 1):
            rows.append((table["name"], pos, name, typ + ("" if notnull else "?")))
    conn.executemany(
        "INSERT OR REPLACE INTO schema_definition (table_name, position, column_name, type)"
        " VALUES (?, ?, ?, ?)", rows)


# --------------------------------------------------------------------------- 读
def _readiness_of(rd, role) -> Optional[ReadinessReport]:
    """readiness 行 → ReadinessReport（无画像的岗位也照样有就绪度，会走这条）。"""
    if rd is None:
        return None
    factors = {}
    if rd["factor"]:
        for pair in rd["factor"].split(";"):
            if "=" in pair:
                k, v = pair.split("=", 1)
                factors[k] = _float(v) or 0.0
    return ReadinessReport(
        role_name=role["role_name"], unit_id=role["unit_id"],
        score=_float(rd["score"]) or 0.0, grade=rd["grade"] or "D",
        label=rd["label"] or "", factors=factors,
        gaps=[g for g in (rd["gaps"] or "").split("；") if g])


def read(db_path: str = DEFAULT_DB_PATH) -> Dict[str, RoleCard]:
    """从库里读回岗位卡（键 ``unit::role``），与 ``RoleCardStore`` 同构。

    用途有二：
      1. 拿到一份 .db 就能用，不需要仓库里的 YAML（交付形态）；
      2. 自检：重建库后读回，与内存里的画像逐字段比对（见 scripts/build_role_db.py --check）。
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        units = {r["unit_id"]: r for r in conn.execute("SELECT * FROM industry_unit")}
        roles = {f"{r['unit_id']}::{r['role_name']}": r
                 for r in conn.execute("SELECT * FROM industry_role")}
        profiles = {f"{r['unit_id']}::{r['role_name']}": r
                    for r in conn.execute("SELECT * FROM role_profile")}

        items: Dict[str, Dict[str, Dict[str, List[str]]]] = {}
        for r in conn.execute("SELECT * FROM role_profile_item ORDER BY position"):
            key = f"{r['unit_id']}::{r['role_name']}"
            items.setdefault(key, {}).setdefault(r["dimension"], {}) \
                 .setdefault(r["field"], []).append(r["value"])

        scores: Dict[str, Dict[str, float]] = {}
        for r in conn.execute("SELECT * FROM capability_score"):
            key = f"{r['unit_id']}::{r['role_name']}"
            scores.setdefault(key, {})[r["dimension"]] = _float(r["score"]) or 0.0

        steps: Dict[int, List[sqlite3.Row]] = {}
        for r in conn.execute("SELECT * FROM workflow_step ORDER BY position"):
            steps.setdefault(r["workflow_id"], []).append(r)
        asserts: Dict[tuple, Dict[str, List[str]]] = {}
        for r in conn.execute("SELECT * FROM step_assertion ORDER BY position"):
            asserts.setdefault((r["workflow_id"], r["step_id"]), {}) \
                   .setdefault(r["kind"], []).append(r["value"])
        workflows: Dict[str, List[dict]] = {}
        for wf in conn.execute("SELECT * FROM workflow ORDER BY unit_id, role_name, position"):
            key = f"{wf['unit_id']}::{wf['role_name']}"
            wf_steps = []
            for st in steps.get(wf["id"], []):
                a = asserts.get((wf["id"], st["step_id"]), {})
                wf_steps.append({
                    "id": st["step_id"], "name": st["name"], "agent_role": st["agent_role"],
                    "playbook": st["playbook"], "runtime": st["runtime"],
                    "preconditions": a.get("preconditions", []),
                    "outputs": a.get("outputs", []), "verify": a.get("verify", []),
                })
            workflows.setdefault(key, []).append({
                "id": wf["wf_id"], "name": wf["name"], "template": wf["template"],
                "trigger": wf["trigger"], "handoff_out": wf["handoff_out"],
                "default": bool(wf["is_default"]), "activation_weight": wf["activation_weight"],
                "steps": wf_steps,
            })

        artifacts: Dict[str, List[dict]] = {}
        for r in conn.execute("SELECT * FROM plugin_artifact ORDER BY position"):
            key = f"{r['unit_id']}::{r['role_name']}"
            arts = {}
            for field in ("name", "kind", "path", "upstream"):
                if r[field] is not None:
                    arts[field] = r[field]
            artifacts.setdefault(key, []).append(arts)

        readiness = {f"{r['unit_id']}::{r['role_name']}": r
                     for r in conn.execute("SELECT * FROM readiness")}

        chain: Dict[str, Dict[str, List[dict]]] = {}
        for r in conn.execute("SELECT * FROM role_chain_ref ORDER BY id"):
            key = f"{r['unit_id']}::{r['role_name']}"
            ref = {"raw": r["raw_value"], "value": r["class_name"], "kind": r["ref_kind"]}
            if r["ref"]:
                ref["ref"] = r["ref"]
            if r["ref_unit"]:
                ref["unit"] = r["ref_unit"]
            if r["ref_index"]:
                src, _, queries = r["ref_index"].partition("|")
                ref["index"] = {"source": src, "query": [q for q in queries.split(";") if q]}
            if r["ref_note"]:
                ref["note"] = r["ref_note"]
            chain.setdefault(key, {}).setdefault(r["field"], []).append(ref)

        cards: Dict[str, RoleCard] = {}
        for key, role in roles.items():
            prof = profiles.get(key)
            unit = units.get(role["unit_id"])
            it = items.get(key, {})
            if prof is None:
                # 库里没有画像行 = 这个岗位确实还没写画像（不是"画像全空"）。
                # 造一份空壳 RoleProfile 会让 read() 与 RoleCardStore 不同构。
                cards[key] = RoleCard(
                    unit_id=role["unit_id"],
                    industry=(unit["industry"] if unit else "") or "",
                    role=role["role_name"], prefix=role["prefix"] or "",
                    description=role["description"] or "",
                    keywords=[k for k in (role["keywords"] or "").split(",") if k],
                    profile=None, workflows=workflows.get(key, []),
                    plugin_artifacts=artifacts.get(key, []),
                    activation={"weight": _float(
                        (workflows.get(key) or [{}])[0].get("activation_weight")) or 1.0},
                    readiness=_readiness_of(readiness.get(key), role),
                    sources=[], chain_refs=chain.get(key, {}),
                )
                continue
            analysis = {
                "mission": prof["mission"] if prof else None,
                "deliverables": it.get("analysis", {}).get("deliverables", []),
                "inputs": it.get("analysis", {}).get("inputs", []),
                "outputs": it.get("analysis", {}).get("outputs", []),
                "kpis": it.get("analysis", {}).get("kpis", []),
            }
            persona = {
                "seniority": prof["seniority"] if prof else None,
                "mindset": prof["mindset"] if prof else None,
                "tone": prof["tone"] if prof else None,
                "decision_rights": it.get("persona", {}).get("decision_rights", []),
                "constraints": it.get("persona", {}).get("constraints", []),
            }
            plugin = {
                "bundle": prof["bundle"] if prof else None,
                "tools": it.get("plugin", {}).get("tools", []),
                "mcp_categories": it.get("plugin", {}).get("mcp_categories", []),
                "install_hint": prof["install_hint"] if prof else None,
                "artifacts": artifacts.get(key, []),   # 与 plugin_artifact 表同源，不重复存
            }
            cap = CapabilityProfile(
                core=it.get("capability", {}).get("core", []),
                tools=it.get("capability", {}).get("tools", []),
                knowledge=it.get("capability", {}).get("knowledge", []),
                soft=it.get("capability", {}).get("soft", []),
                scoring=scores.get(key, {}),
            )
            sh = it.get("stakeholders", {})
            profile = RoleProfile(
                role=role["role_name"], analysis=analysis, persona=persona, plugin=plugin,
                workflow={}, capability=cap,
                stakeholders=StakeholderChain(
                    upstream=[c["value"] for c in chain.get(key, {}).get("upstream", [])],
                    downstream=[c["value"] for c in chain.get(key, {}).get("downstream", [])],
                    beneficiaries=sh.get("beneficiaries", []),
                    blockers=sh.get("blockers", []),
                    incentives=sh.get("incentives", []),
                    risk_notes=sh.get("risk_notes", []),
                ),
                source=prof["source_file"] if prof else "",
            )
            report = _readiness_of(readiness.get(key), role)

            cards[key] = RoleCard(
                unit_id=role["unit_id"],
                industry=(unit["industry"] if unit else "") or "",
                role=role["role_name"], prefix=role["prefix"] or "",
                description=role["description"] or "",
                keywords=[k for k in (role["keywords"] or "").split(",") if k],
                profile=profile, workflows=workflows.get(key, []),
                plugin_artifacts=artifacts.get(key, []),
                activation={"weight": _float((workflows.get(key) or [{}])[0].get("activation_weight")) or 1.0},
                readiness=report, sources=[prof["source_file"]] if prof and prof["source_file"] else [],
                chain_refs=chain.get(key, {}),
            )
        return cards
    finally:
        conn.close()


def stats(db_path: str = DEFAULT_DB_PATH) -> Dict[str, object]:
    """库里有什么（表行数 + 体积 + 构建溯源），给人看的一眼数。"""
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"库不存在：{db_path}（先跑 scripts/build_role_db.py）")
    conn = sqlite3.connect(db_path)
    try:
        names = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        rows = {}
        for name in names:
            rows[name] = conn.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
        version = conn.execute(
            "SELECT version, built_at, source, generator FROM schema_version"
            " ORDER BY built_at DESC LIMIT 1").fetchone()
        return {
            "path": db_path, "bytes": os.path.getsize(db_path),
            "tables": rows, "total_rows": sum(rows.values()),
            "version": version[0] if version else None,
            "built_at": version[1] if version else None,
            "source": version[2] if version else None,
            "generator": version[3] if version else None,
        }
    finally:
        conn.close()


def query(db_path: str, sql: str) -> List[tuple]:
    """只读查询（写语句一律拒绝）—— 库要能被真用，不只是被数行数。"""
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"库不存在：{db_path}")
    head = sql.strip().split(None, 1)[0].lower() if sql.strip() else ""
    if head not in ("select", "with", "pragma"):
        raise PermissionError("只允许只读查询（select / with / pragma）")
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()
