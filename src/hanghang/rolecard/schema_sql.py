"""行业类 / 利益链条的数据库形态（DDL + 数据字典）

为什么要有这层：词表拆成目录之后，仓库里那份回答「有什么类、怎么查公司」；
真正的名录、客户档案、供应商台账在 CRM / 企业名录 / ATS / 内部主数据里。
中间需要一个**结构**，让两边对得上：类目表、别名表、索引源表、
岗位引用表（谁在哪个字段引用了哪个类）。这才是能查、能 join、能管的东西。

这里只产出 schema 和数据字典文本，不连接任何数据库、不落凭据。
``ddl`` 用 SQLite 语法（最严也最可移植，PostgreSQL 只需把 AUTOINCREMENT 换掉），
``data`` 是仓库里能落盘的部分（类目/别名/索引/引用），公司名录**永远不进仓库**。
"""
from __future__ import annotations

from typing import Dict, List, Tuple

DDL = """\
-- ===========================================================================
-- 行业类与利益链条 · 结构（由 scripts/export_class_db.py 生成，勿手改）
--
-- 三张主表 + 两张关联表，回答四个问题：
--   1. industry_class   有哪些类目，分别是什么 kind
--   2. class_alias      同一个类目的其他叫法（收敛同义词，防止一地鸡毛）
--   3. class_index_src  这个类目去哪个系统、用什么查询式查具体公司
--   4. role_chain_ref   哪个岗位的哪个字段引用了哪个类目（反查靠它）
--
-- **本 schema 不含公司名录表**。企业名录/客户档案住在 CRM / ATS / 企业名录里，
-- 靠 class_index_src 声明的来源去查。把名录塞进仓库既不合规也不通用。
-- ===========================================================================

CREATE TABLE IF NOT EXISTS industry_class (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,     -- 类目名：钢材加工 / 品牌方 / 用人部门
    kind        TEXT    NOT NULL,            -- 制造/服务/渠道/机构/内部组织/需求方/阻碍/单元
    label       TEXT,                        -- 展示名（单元类目用中文行业名）
    is_entity   INTEGER NOT NULL DEFAULT 1,  -- 1=实体（可查到公司） 0=原因/接口/输入
    source_file TEXT    NOT NULL             -- 声明它的文件，改词表时知道动哪
);

CREATE TABLE IF NOT EXISTS class_alias (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    class_name TEXT NOT NULL,                -- 归到哪个类目
    alias      TEXT NOT NULL UNIQUE,         -- 别名/旧叫法
    source_file TEXT NOT NULL,
    FOREIGN KEY (class_name) REFERENCES industry_class(name)
);

CREATE TABLE IF NOT EXISTS class_index_src (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    class_name TEXT    NOT NULL,
    source     TEXT    NOT NULL,             -- CRM / 企业名录 / ATS / 内部主数据
    query_expr TEXT    NOT NULL,             -- 查询式：钢材{加工|剪切|开平}
    FOREIGN KEY (class_name) REFERENCES industry_class(name)
);

CREATE TABLE IF NOT EXISTS role_chain_ref (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id    TEXT    NOT NULL,             -- 行业单元
    role_name  TEXT    NOT NULL,             -- 岗位
    field      TEXT    NOT NULL,             -- upstream/downstream/beneficiaries/blockers
    raw_value  TEXT    NOT NULL,             -- 画像里原本写的东西
    class_name TEXT    NOT NULL,             -- 归一后的类目
    FOREIGN KEY (class_name) REFERENCES industry_class(name)
);

CREATE INDEX IF NOT EXISTS idx_chain_ref_class ON role_chain_ref(class_name);
CREATE INDEX IF NOT EXISTS idx_chain_ref_role  ON role_chain_ref(unit_id, role_name);
CREATE INDEX IF NOT EXISTS idx_index_src_class ON class_index_src(class_name);
"""

# 天生不是「实体」的 kind：不该有公司索引，也不该被当成可查名录
NON_ENTITY_KINDS = ("接口", "渠道", "需求", "输入", "阻碍", "内部组织", "资源", "岗位类", "单元")


def _q(value) -> str:
    """SQL 字符串字面量（不引第三方依赖，单引号翻倍即标准转义）。"""
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def entity_rows(classes) -> List[Tuple[str, str, str, int, str]]:
    rows = []
    for name, spec in sorted(classes.classes.items()):
        spec = spec or {}
        kind = str(spec.get("kind", ""))
        rows.append((
            name,
            kind,
            str(spec.get("label") or "") or None,
            0 if kind in NON_ENTITY_KINDS else 1,
            classes.sources.get(name, ""),
        ))
    return rows


def data_sql(classes, usage: Dict[str, dict]) -> str:
    """仓库侧可落盘的数据：类目 / 别名 / 索引源 / 岗位引用。不含公司名录。"""
    lines = ["-- 行业类数据（类目 + 别名 + 索引源 + 岗位引用）；公司名录不在其中。", ""]

    lines.append("-- industry_class")
    for name, kind, label, is_entity, src in entity_rows(classes):
        lines.append(
            "INSERT INTO industry_class (name, kind, label, is_entity, source_file) VALUES "
            f"({_q(name)}, {_q(kind)}, {_q(label)}, {is_entity}, {_q(src)});"
        )

    lines.append("")
    lines.append("-- class_alias")
    for canon, names in sorted(classes.aliases.items()):
        src = classes.sources.get(canon, "")
        for alias in (names if isinstance(names, list) else [names]):
            lines.append(
                "INSERT INTO class_alias (class_name, alias, source_file) VALUES "
                f"({_q(canon)}, {_q(alias)}, {_q(src)});"
            )

    lines.append("")
    lines.append("-- class_index_src（只存检索方式，不存公司）")
    for name, spec in sorted(classes.classes.items()):
        idx = (spec or {}).get("index")
        if not isinstance(idx, dict):
            continue
        source = str(idx.get("source") or "")
        for expr in (idx.get("query") or []):
            lines.append(
                "INSERT INTO class_index_src (class_name, source, query_expr) VALUES "
                f"({_q(name)}, {_q(source)}, {_q(expr)});"
            )

    lines.append("")
    lines.append("-- role_chain_ref（类目 → 被哪些岗位引用）")
    for name, item in sorted(usage.items()):
        for ref in item.get("used_by") or []:
            lines.append(
                "INSERT INTO role_chain_ref (unit_id, role_name, field, raw_value, class_name) "
                f"VALUES ({_q(ref.get('unit'))}, {_q(ref.get('role'))}, {_q(ref.get('field'))}, "
                f"{_q(ref.get('raw') or name)}, {_q(name)});"
            )
    return "\n".join(lines) + "\n"


def dictionary_md(classes, usage: Dict[str, dict]) -> str:
    """人看的数据字典：每个类目归哪个来源、被多少岗位引用、怎么查公司。"""
    by_kind: Dict[str, list] = {}
    for name, spec in classes.classes.items():
        by_kind.setdefault(str((spec or {}).get("kind", "")), []).append(name)

    out = [
        "# 行业类数据字典",
        "",
        "由 `scripts/export_class_db.py` 生成；口径来源 `data/industry-classes.yaml`",
        "及其拆分的域文件（`data/industry-classes/*.yaml`）。",
        "",
        f"类目 {len(classes.classes)} 条 / 别名 {sum(len(v) for v in classes.aliases.values())} 条"
        f" / 已接索引 {sum(1 for s in classes.classes.values() if (s or {}).get('index'))} 条。",
        "",
        "**公司名录不在本仓库**：`index` 只写「去哪个系统、用什么查询式查」，",
        "具体企业由运行时经 CRM / 企业名录 / ATS / 内部主数据检索。",
        "",
    ]
    for kind in sorted(by_kind):
        out.append(f"## {kind}（{len(by_kind[kind])}）")
        out.append("")
        out.append("| 类目 | 索引源 | 查询式 | 被引用 |")
        out.append("|---|---|---|---|")
        for name in sorted(by_kind[kind]):
            spec = classes.classes.get(name) or {}
            idx = spec.get("index") or {}
            used = len((usage.get(name) or {}).get("used_by") or [])
            out.append(
                f"| {name} | {idx.get('source') or '—'} "
                f"| {'; '.join(idx.get('query') or []) or '—'} | {used} 处 |"
            )
        out.append("")
    return "\n".join(out)
