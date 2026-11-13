"""行业类 / 利益链条的数据库结构（DDL 单源，双方言）

为什么要有这层：词表拆成目录之后，仓库里那份回答「有什么类、怎么查公司」；
真正的名录、客户档案、供应商台账在 CRM / 企业名录 / ATS / 内部主数据里。
中间需要**结构**，让两边对得上：类目表、别名表、索引源表、岗位引用表。
这才是能查、能 join、能管的东西。

这里只管 schema 文本，不连接任何数据库、不落凭据。
同一个表定义渲染成两种方言：``sqlite``（零运维、能直接进仓库）与
``postgresql``（真接服务器时用）。表名/列名两边一致，切库只改方言参数。
``data`` 是仓库里能落盘的部分（类目/别名/索引/引用），公司名录**永远不进仓库**。
"""
from __future__ import annotations

from typing import Dict, List, Tuple

# kind 分类：天生不是「实体」（不该有公司索引，也不该被当成可查名录）
NON_ENTITY_KINDS = ("接口", "渠道", "需求", "输入", "阻碍", "内部组织", "资源", "岗位类", "单元")

SCHEMA_VERSION = "3.0.0"

# ---------------------------------------------------------------------------- 表定义
# 单一来源：列定义写一份，两种方言各自拼接自增主键与类型。
# 新增表只改这里，DDL / 建库 / 自检自动跟上（脚本与库不会各说各话）。
_TABLES: List[dict] = [
    {
        "name": "schema_version",
        "comment": "结构版本与构建溯源：拿到库先知道它是哪版、由什么生成",
        "columns": [
            ("version", "text", True),
            ("built_at", "text", True),
            ("source", "text", True),
            ("generator", "text", True),
        ],
        "pk": ("version",),
    },
    {
        "name": "industry_class",
        "comment": "类目：钢材加工 / 品牌方 / 用人部门 …（稳定、可复用、可跨行业）",
        "columns": [
            ("id", "int", False),
            ("name", "text", True),          # 类目名
            ("kind", "text", True),          # 制造/服务/渠道/机构/内部组织/需求方/阻碍/单元
            ("label", "text", False),        # 展示名（单元类目用中文行业名）
            ("is_entity", "int", True),      # 1=实体（可查到公司） 0=原因/接口/输入
            ("source_file", "text", True),   # 声明它的文件，改词表时知道动哪
        ],
        "pk": ("id",),
        "unique": [("name",)],
    },
    {
        "name": "class_alias",
        "comment": "别名：同一个东西的多种叫法收敛到一个 class_name",
        "columns": [
            ("id", "int", False),
            ("class_name", "text", True),
            ("alias", "text", True),
            ("source_file", "text", True),
        ],
        "pk": ("id",),
        "unique": [("alias",)],
        "fk": [("class_name", "industry_class", "name")],
    },
    {
        "name": "class_index_src",
        "comment": "索引源：这个类去哪个系统、用什么查询式查具体公司（只存检索方式）",
        "columns": [
            ("id", "int", False),
            ("class_name", "text", True),
            ("source", "text", True),
            ("query_expr", "text", True),
        ],
        "pk": ("id",),
        "fk": [("class_name", "industry_class", "name")],
    },
    {
        "name": "role_chain_ref",
        "comment": "岗位引用：哪个岗位的哪个字段引用了什么（类目/接口/岗位三类落点）",
        "columns": [
            ("id", "int", False),
            ("unit_id", "text", True),          # 引用方
            ("role_name", "text", True),
            ("field", "text", True),            # upstream/downstream/beneficiaries/blockers
            ("raw_value", "text", True),        # 画像里原本写的
            ("class_name", "text", True),       # 归一后的说法
            ("ref_kind", "text", True),         # industry_class / interface / role
            ("ref_unit", "text", False),        # ref_kind=role 且跨单元时指向哪个单元
            ("ref", "text", False),             # 完整引用 "industry_class:钢材加工"
            ("ref_index", "text", False),       # 类目索引快照 "企业名录|钢材{加工|剪切}"
            ("ref_note", "text", False),        # 类目 kind 提示
        ],
        "pk": ("id",),
        # 刻意不外键到 industry_class：链上除了类目还能落「接口」和「岗位」，
        # 那两类名字本来就不在类目表里，硬加外键会让它们被误当成缺失类目。
    },
    # ---------------------------------------------------------------- 岗位画像层
    {
        "name": "industry_unit",
        "comment": "行业单元（M2 注册表落库）：一个行业一套岗位",
        "columns": [
            ("unit_id", "text", True),
            ("industry", "text", True),
            ("industry_alias", "text", False),   # 逗号分隔（切库后可改 jsonb）
            ("version", "text", False),
            ("source_file", "text", False),
        ],
        "pk": ("unit_id",),
    },
    {
        "name": "industry_role",
        "comment": "岗位清单（注册表）：岗位 → 前缀 / 触发词 / 简介，是画像卡的事实来源",
        "columns": [
            ("unit_id", "text", True),
            ("role_name", "text", True),
            ("prefix", "text", False),
            ("description", "text", False),
            ("keywords", "text", False),
        ],
        "pk": ("unit_id", "role_name"),
        "fk": [("unit_id", "industry_unit", "unit_id")],
    },
    {
        "name": "role_profile",
        "comment": "岗位画像基线：六维评估的元信息（六维正文分表存）",
        "columns": [
            ("unit_id", "text", True),
            ("role_name", "text", True),
            ("mission", "text", False),
            ("seniority", "text", False),
            ("mindset", "text", False),
            ("tone", "text", False),
            ("bundle", "text", False),
            ("install_hint", "text", False),
            ("scoring_avg", "text", False),   # 能力均分（兼容各库类型，读写走 floats）
            ("source_file", "text", False),
        ],
        "pk": ("unit_id", "role_name"),
        "fk": [("unit_id", "industry_unit", "unit_id")],
    },
    {
        "name": "role_profile_item",
        "comment": "画像条目：六维里的清单型字段一条一行（deliverables / inputs / kpis …）",
        "columns": [
            ("unit_id", "text", True),
            ("role_name", "text", True),
            ("dimension", "text", True),      # analysis/persona/plugin/stakeholders/capability/…
            ("field", "text", True),          # deliverables / inputs / kpis / upstream …
            ("value", "text", True),
            ("position", "int", True),        # 原始顺序，渲染时按它排
        ],
        "pk": ("unit_id", "role_name", "dimension", "field", "position"),
        "fk": [(("unit_id", "role_name"), "role_profile", None)],   # 复合外键
    },
    {
        "name": "capability_score",
        "comment": "能力评分（0-5 五维）：domain/tooling/judging/execution/comms",
        "columns": [
            ("unit_id", "text", True),
            ("role_name", "text", True),
            ("dimension", "text", True),
            ("score", "text", True),          # 数值以文本存，读写统一转 float
        ],
        "pk": ("unit_id", "role_name", "dimension"),
        "fk": [(("unit_id", "role_name"), "role_profile", None)],
    },
    {
        "name": "workflow",
        "comment": "工作流：模板 + 岗位覆盖（按步骤 id 合并）",
        "columns": [
            ("id", "int", False),
            ("unit_id", "text", True),
            ("role_name", "text", True),
            ("wf_id", "text", True),
            ("name", "text", False),
            ("template", "text", False),
            ("trigger", "text", False),
            ("handoff_out", "text", False),
            ("is_default", "int", True),
            ("activation_weight", "text", False),
            ("position", "int", True),
        ],
        "pk": ("id",),
        "unique": [("unit_id", "role_name", "wf_id")],
        # 挂在岗位清单上，不挂在画像上：工作流来自模板 + 注册表信号，
        # 没写画像的岗位照样有可执行工序（只是没被评分）。挂 role_profile 会让
        # "画像后补"的岗位连工序都落不进去。
        "fk": [(("unit_id", "role_name"), "industry_role", None)],
    },
    {
        "name": "workflow_step",
        "comment": "工作流步骤：谁干、按什么 playbook 干、怎么验、用什么 runtime",
        "columns": [
            ("workflow_id", "int", True),
            ("step_id", "text", True),
            ("name", "text", False),
            ("agent_role", "text", False),
            ("playbook", "text", False),
            ("runtime", "text", False),       # agent / n8n / code
            ("position", "int", True),
        ],
        "pk": ("workflow_id", "step_id"),
        "fk": [("workflow_id", "workflow", "id")],
    },
    {
        "name": "step_assertion",
        "comment": "步骤断言：preconditions / outputs / verify 一条一行",
        "columns": [
            ("workflow_id", "int", True),
            ("step_id", "text", True),
            ("kind", "text", True),
            ("value", "text", True),
            ("position", "int", True),
        ],
        "pk": ("workflow_id", "step_id", "kind", "position"),
    },
    {
        "name": "plugin_artifact",
        "comment": "插件封装：可挂载的技能文件（只记路径、类型与来源，不存凭据）",
        "columns": [
            ("unit_id", "text", True),
            ("role_name", "text", True),
            ("name", "text", True),
            ("kind", "text", False),
            ("path", "text", False),
            ("upstream", "text", False),
            ("position", "int", True),
        ],
        "pk": ("unit_id", "role_name", "name"),
        # 与 artifact 的归属一致：技能包挂岗位，不挂工作流。写入侧原本靠「每岗必有
        # workflow」才把 artifact 写进去，这条 FK 让「没工序但有技能包」立刻报错，
        # 而不是静默丢行。
        "fk": [(("unit_id", "role_name"), "industry_role", None)],
    },
    {
        "name": "readiness",
        "comment": "就绪度：分数 + 评级 + 缺口（渲染产物视图，不是人工数据）",
        "columns": [
            ("unit_id", "text", True),
            ("role_name", "text", True),
            ("score", "text", True),
            ("grade", "text", False),
            ("label", "text", False),
            ("factor", "text", False),        # 因子快照，"k=v;k=v"
            ("gaps", "text", False),          # 缺口快照，一行一条用 ；分隔
        ],
        "pk": ("unit_id", "role_name"),
    },
]

_TYPES = {
    "sqlite": {
        "int": "INTEGER",
        "text": "TEXT",
        "pk_auto": "INTEGER PRIMARY KEY AUTOINCREMENT",
    },
    "postgresql": {
        "int": "INTEGER",
        "text": "TEXT",
        "pk_auto": "INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY",
    },
}

_INDEXES = [
    ("idx_chain_ref_class", "role_chain_ref", ("class_name",)),
    ("idx_chain_ref_role", "role_chain_ref", ("unit_id", "role_name")),
    ("idx_index_src_class", "class_index_src", ("class_name",)),
    ("idx_alias_class", "class_alias", ("class_name",)),
    ("idx_role_profile_item", "role_profile_item", ("dimension", "field")),
    ("idx_workflow_role", "workflow", ("unit_id", "role_name")),
    ("idx_artifact_role", "plugin_artifact", ("unit_id", "role_name")),
]


def _q_ident(name: str) -> str:
    """标识符引用（保留字兜底），两边方言都用双引号。"""
    return '"' + str(name).replace('"', '""') + '"'


def _column_sql(col: Tuple[str, str, bool], dialect: str) -> str:
    name, typ, notnull = col
    if name == "id" and not notnull:
        return f"    {'id':<18}{_TYPES[dialect]['pk_auto']}"
    sql = f"    {name:<18}{_TYPES[dialect][typ]}"
    if notnull:
        sql += " NOT NULL"
    return sql


def ddl(dialect: str = "sqlite") -> str:
    """渲染完整 DDL（两种方言表名列名一致）。"""
    if dialect not in _TYPES:
        raise ValueError(f"未知方言: {dialect}")
    out = [
        "-- ===========================================================================",
        f"-- 岗位 / 行业类 / 利益链条 · 库结构（{dialect}）",
        f"-- schema {SCHEMA_VERSION} · 由 scripts/build_role_db.py 生成，勿手改",
        "--",
        "-- 设计要点：",
        "--   1. 一张表只回答一个问题，能 join 的不塞字段；",
        "--   2. **没有公司名录表**：企业名录住 CRM / 企业名录 / ATS / 内部主数据，",
        "--      这里只存 class_index_src（去哪个系统、用什么查询式），名录不进库；",
        "--   3. 列表型字段（交付物/KPI/上下游）一条一行，能按值检索、能统计，",
        "--      不是整段 JSON 塞一列；",
        "--   4. 数值型（评分/就绪度）以 TEXT 存，读写统一走 float，",
        "--      避免各库类型差异导致同一份数据在 SQLite/PG 行为不同。",
        "-- ===========================================================================",
        "",
    ]
    for table in _TABLES:
        cols = [_column_sql(c, dialect) for c in table["columns"]]
        has_auto_pk = any(c[0] == "id" and not c[2] for c in table["columns"])
        if not has_auto_pk:
            pk = ",\n    ".join(_q_ident(c) for c in table["pk"])
            cols.append(f"    PRIMARY KEY ({pk})")
        for uniq in table.get("unique") or []:
            cols.append("    UNIQUE (" + ", ".join(_q_ident(c) for c in uniq) + ")")
        # 复合外键（cite 表用当前表的分组）与普通外键都在这层落
        for fk in table.get("fk") or []:
            col, ref_table, ref_col = fk[0], fk[1], fk[2]
            if ref_col is None:      # 复合外键：指向被引用表的主键
                refs = next(t["pk"] for t in _TABLES if t["name"] == ref_table)
                src = (col,) if isinstance(col, str) else tuple(col)
                cols.append(
                    f"    FOREIGN KEY ({', '.join(_q_ident(c) for c in src)}) "
                    f"REFERENCES {_q_ident(ref_table)}({', '.join(_q_ident(c) for c in refs)})"
                )
            else:
                cols.append(
                    f"    FOREIGN KEY ({_q_ident(col)}) "
                    f"REFERENCES {_q_ident(ref_table)}({_q_ident(ref_col)})"
                )
        body = ",\n".join(cols)
        out.append(f"-- {table['comment']}")
        out.append(f"CREATE TABLE IF NOT EXISTS {_q_ident(table['name'])} (")
        out.append(body)
        out.append(");")
        out.append("")

    for name, table, cols in _INDEXES:
        out.append(
            f"CREATE INDEX IF NOT EXISTS {name} ON {_q_ident(table)}"
            f"({', '.join(_q_ident(c) for c in cols)});"
        )
    out.append("")
    return "\n".join(out)


CLASS_TABLES = ("industry_class", "class_alias", "class_index_src", "role_chain_ref")


def class_table_ddl(dialect: str = "sqlite") -> str:
    """只渲染类目相关四张表（export_class_db.py 的口径快照用）。"""
    full = ddl(dialect)
    keep, out = None, []
    for line in full.splitlines():
        m = line.startswith("CREATE TABLE IF NOT EXISTS \"")
        if m:
            keep = line.split('"')[1] in CLASS_TABLES
        elif line.startswith("CREATE INDEX"):
            keep = any(f"\"{t}\"(" in line for t in CLASS_TABLES)
        elif line.startswith("-- ===") or line.startswith("--"):
            pass          # 头注释保留在调用方，这里不重复
        if keep:
            out.append(line)
        elif not line.strip() and keep is not None:
            out.append("")
            keep = None
    return "\n".join(out).strip() + "\n"


def tables(dialect: str = "sqlite") -> List[str]:
    return [t["name"] for t in _TABLES]


# 兼容旧入口：默认 SQLite 方言
DDL = ddl("sqlite")


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
    lines.append("-- role_chain_ref（类目 → 被哪些岗位引用；只落类目形态，岗位/接口形态见实库）")
    for name, item in sorted(usage.items()):
        for ref in item.get("used_by") or []:
            lines.append(
                "INSERT INTO role_chain_ref (unit_id, role_name, field, raw_value, class_name,"
                " ref_kind, ref_unit) VALUES "
                f"({_q(ref.get('unit'))}, {_q(ref.get('role'))}, {_q(ref.get('field'))}, "
                f"{_q(ref.get('raw') or name)}, {_q(name)}, 'industry_class', NULL);"
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
