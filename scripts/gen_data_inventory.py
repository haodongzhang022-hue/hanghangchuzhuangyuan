#!/usr/bin/env python3
"""数据盘存清单：这份仓库里到底有哪些数据、各自是权威源还是产物、在平台上落在哪。

回答的是「东西都在哪」——不是靠人记，而是生成一份可校验的清单：

    docs/industry/data-inventory.md     进版本库（可评审，被知识库切成片段）
    out/industry-db/data-inventory.csv  进导出产物（BI / 交接直接用）

为什么要生成而不是手写：手写的清单会在第一次改数据时就过期，而过期的清单比没有
清单更坏 —— 它会让人相信某份文件还在被用。`--check` 让产物与数据不许分叉（CI 拦）。

用法：
  python3 scripts/gen_data_inventory.py            # 重生成（md + csv）
  python3 scripts/gen_data_inventory.py --check    # 只校验进库的 md 是否过期（CI）

CSV 不进 `--check`：它落在被 .gitignore 忽略的 out/ 下，干净克隆里必然不存在，
算进去就等于一条永远红的守卫。
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

import yaml                                                    # noqa: E402

from hanghang.engine import industry_schema                    # noqa: E402
from hanghang.engine.industry_db import IndustryDatabase        # noqa: E402

DOC = os.path.join(ROOT, "docs", "industry", "data-inventory.md")
CSV_OUT = os.path.join(ROOT, "out", "industry-db", "data-inventory.csv")

# 权威源：文件 → (盘什么, 谁在读它, 一句话说明)
SOURCES = [
    ("data/industry-occupations.yaml", "occupations",
     "IndustryDatabase", "职业原子表：最小单目标，不带归属字段"),
    ("data/industry-partitions.yaml", "partitions",
     "IndustryDatabase", "分区（职业聚类结果）：付费方/供给结构/产值口径/建不建单元"),
    ("data/occupation-memberships.yaml", "memberships",
     "OccupationAxis", "归属边：职业 × 分区 × 轴 × 权重（权重不是概率）"),
    ("data/industry-scales.yaml", "scales",
     "ScaleLedger", "六口径规模账：盈利/资产/估值/资源消耗（gdp 与就业在 partition 上）"),
    ("data/industry-money-flows.yaml", "flows",
     "MoneyFlowBook", "资金流守恒账：部门 + 行业池 + 双边记账 + 对账口径"),
    ("data/industry-official-baseline.yaml", "benchmarks",
     "OfficialBaseline", "官方口径基准：逐年表值 + 分区↔基准对表关系"),
    ("data/industry-input-output.yaml", "accounts",
     "InputOutputBook", "投入产出账：生产法三端 + 中间投入构成 + 池切分锚点"),
    ("data/industry-strategy.yaml", "partitions",
     "StrategyView", "行业战略视图：价值链/利润池/杠杆/驱动/风险/AI 承接面/岗位落点"
                     "（粒度只到岗位/角色，工序与话术由 AI 上岗后补）"),
    ("data/industry-classes.yaml", "aliases",
     "ClassStore", "行业类词表汇总入口（类目本体在 data/industry-classes/*.yaml），"
                   "公司靠索引现查不落库"),
    ("data/unit-index.yaml", "units",
     "Registry", "行业单元索引：路由的注册表"),
    ("data/coverage-target.yaml", "targets",
     "CoverageTracker", "覆盖目标全集（分母）与各行业建议搜集渠道"),
    ("data/rolecard-schema.yaml", "version",
     "rolecard", "岗位卡字段契约（顶层是契约元信息，字段定义在 required/optional 段）"),
]

# 结构产物：进版本库（契约要能被评审），数据不进
STRUCTURAL = [
    ("data/db/industry/00-schema.sqlite.sql", "SQLite DDL",
     "scripts/export_industry_db.py", "买服务器直接建库用（SQLite 方言）"),
    ("data/db/industry/00-schema.postgresql.sql", "PostgreSQL DDL",
     "scripts/export_industry_db.py", "买服务器直接建库用（PG 方言）"),
    ("data/db/00-schema.sqlite.sql", "岗位画像库 DDL",
     "scripts/build_role_db.py", "另一套库：岗位画像/工序/就绪度"),
    ("data/db/00-schema.postgresql.sql", "岗位画像库 DDL (PG)",
     "scripts/build_role_db.py", "同上，PG 方言"),
    ("data/db/00-class-tables.sql", "行业类库 DDL",
     "scripts/export_class_db.py", "行业类词表建库结构"),
]


def _count(path: str, key: str) -> int:
    """数一下这份源里有多少条。数不出来就返回 -1，由清单直接暴露 ——
    悄悄显示 0 会让人以为文件是空的。"""
    try:
        with open(os.path.join(ROOT, path), encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except Exception:                                   # noqa: BLE001
        return -1
    v = data.get(key)
    if isinstance(v, list):
        return len(v)
    if isinstance(v, dict):
        return len(v)
    if isinstance(v, str):
        # 顶层给的是标量（version 这类）：这份文件盘的不是条目数，别硬凑一个 0。
        # 返回 -1 会在清单里显示"不适用"，而不是一个看起来像真的 0。
        return -1
    return -1


def _lines(path: str) -> int:
    try:
        with open(os.path.join(ROOT, path), encoding="utf-8") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return -1


def _size(path: str) -> str:
    p = os.path.join(ROOT, path)
    if not os.path.exists(p):
        return "—"
    n = os.path.getsize(p)
    return f"{n / 1024:.0f} KB" if n >= 1024 else f"{n} B"


def rows() -> list:
    """一行一份文件。role 三档：source（权威源）/ structure（结构产物）/ derived（导出）。"""
    db = IndustryDatabase()
    snap = db.compute()
    counts = industry_schema.counts(db, snap)
    out = []
    for path, key, reader, desc in SOURCES:
        out.append({
            "path": path, "role": "source", "items": _count(path, key),
            "unit": key, "reader": reader, "size": _size(path),
            "platform": "仓库源码 · 知识库切片 · 可直接评审回滚",
            "desc": desc,
        })
    for path, label, gen, desc in STRUCTURAL:
        out.append({
            "path": path, "role": "structure", "items": _lines(path),
            "unit": "行", "reader": gen, "size": _size(path),
            "platform": "仓库源码（结构是契约，数据不进版本库）",
            "desc": f"{label}：{desc}",
        })
    # 导出产物：不落版本库，运行时生成
    for name, desc in (
            ("industry-db.json", "全量 JSON（含四本账），给 BI/知识库直接吃"),
            ("partitions.csv", "分区扁平表"),
            ("occupations.csv", "职业扁平表（含多视角边）"),
            ("scales.csv", "六口径一行一个口径，缺的也占一行"),
            ("money-nodes.csv", "资金流节点（带 inflow/outflow/gap_ratio）"),
            ("money-flows.csv", "资金流明细（memo 列区分「摊开看」与真钱）"),
            ("baseline-check.csv", "官方基准对表结论（一分区一行，带偏差）"),
            ("io-accounts.csv", "生产法三端 + 增加值率 + 能否切分"),
            ("io-input-plan.csv", "中间投入构成还缺什么、卡住哪一步、谁在消费这个分区"),
            ("strategy.csv", "行业战略视图：价值链/利润池/AI 承接面/岗位落点"),
            ("data-inventory.csv", "本清单自身"),
            ("industry.sqlite", "单文件库（13 表）"),
            ("00-schema.sqlite.sql", "建库 DDL（SQLite）"),
            ("00-schema.postgresql.sql", "建库 DDL（PostgreSQL）"),
            ("10-data.sql", "与方言无关的数据 SQL（10-data.sql 是文件名，非表数）")):
        p = os.path.join("out", "industry-db", name)
        out.append({
            "path": p,
            "role": "derived", "items": "", "unit": "",
            "reader": "industry export", "size": "运行时生成",
            "platform": "导出产物（不进版本库，可由 yaml 秒级重建）",
            "desc": desc,
        })
    return out, counts, snap


def render_md() -> str:
    data, counts, snap = rows()
    lines = [
        "# 数据盘存清单", "",
        "由 `scripts/gen_data_inventory.py` 生成，**请勿手改**。"
        "改动数据后重跑本脚本，`--check` 会在 CI 里拦住过期产物。", "",
        "## 一句话：东西都在哪", "",
        "| 落点 | 是什么 | 谁在用 |", "|---|---|---|",
        "| `data/*.yaml` | 权威源：人工维护、可评审、可回滚 | 引擎 + 知识库切片 |",
        "| `data/db/**/*.sql` | 结构产物：DDL 进版本库（契约），数据不进 | 客户建库 / CI 往返自检 |",
        "| `out/industry-db/*` | 导出产物：`industry export` 生成 | BI / 制品库 / 交接 |",
        "| CNB 知识库 | `**/*.md` 自动切片（排除 `poc/**`） | 检索问答 |",
        "", "## 一、权威源（改数据只改这些）", "",
        "| 文件 | 条目 | 被谁读 | 大小 | 说明 |", "|---|---|---|---|---|",
    ]
    for r in data:
        if r["role"] != "source":
            continue
        n = (f"{r['items']} {r['unit']}" if r["items"] >= 0
             else "不适用（契约/索引文件，非条目）")
        lines.append(f"| `{r['path']}` | {n} | `{r['reader']}` "
                     f"| {r['size']} | {r['desc']} |")
    lines += ["", "## 二、结构产物（进版本库，是契约）", "",
              "| 文件 | 行数 | 生成者 | 说明 |", "|---|---|---|---|"]
    for r in data:
        if r["role"] != "structure":
            continue
        lines.append(f"| `{r['path']}` | {r['items']} | `{r['reader']}` "
                     f"| {r['desc']} |")
    lines += ["", "## 三、导出产物（不进版本库，可秒级重建）", "",
              "```bash",
              "python3 src/hanghang/cli/main.py industry export --out out/industry-db",
              "```", "",
              "| 文件 | 说明 |", "|---|---|"]
    for r in data:
        if r["role"] != "derived":
            continue
        lines.append(f"| `{r['path']}` | {r['desc']} |")
    lines += ["", "## 四、库里的行数（导出时实测）", "",
              "| 表 | 行数 |", "|---|---|"]
    for name, n in counts.items():
        lines.append(f"| `{name}` | {n} |")
    lines += ["", f"合计 {sum(counts.values())} 行 / {len(counts)} 张表"
              "（`export_industry_db.py --check` 会真灌一份临时库再读回来比对）。", "",
              "## 五、五本账各守什么", "",
              "| 账 | 文件 | 守的一件事 | 抓得住什么 |", "|---|---|---|---|",
              "| 六口径规模账 | `data/industry-scales.yaml` | 行业不因产值没统计就整体隐身 "
              "| 任一格有数就在表里；缺的格子必须写原因 |",
              "| 资金流守恒账 | `data/industry-money-flows.yaml` | 钱不会凭空生灭 "
              "| 节点与外部口径对账偏差超 10% 即报；`memo` 边区分「摊开看」与真钱 |",
              "| 官方口径基准 | `data/industry-official-baseline.yaml` "
              "| `high` 置信度必须可核对 | 同口径 + 同年份对表；口径不同（`incomparable`）不许相减 |",
              "| 投入产出账 | `data/industry-input-output.yaml` | 切分不重复计 "
              "| 生产法恒等式三端闭合；GMV/成本总额不许当增加值锚点 |",
              "| 行业战略视图 | `data/industry-strategy.yaml` "
              "| 钱为什么在这、AI 该站哪一段 "
              "| 粒度只到岗位/角色：工序与话术由 AI 上岗后补，写死在这里的那版一定过期 |", "",
              "## 六、平台路径", "",
              "- 仓库内：`data/`（源）、`data/db/industry/`（结构）、`out/industry-db/`（导出）",
              "- 知识库：本文件与 `docs/industry/*.md` 会被切成片段供检索"
              "（`.cnb.yml` 的 `knowledge update`，include `**/*.md`、exclude `poc/**`）",
              "- 库：`data/db/industry/00-schema.{sqlite,postgresql}.sql` + "
              "`out/industry-db/10-data.sql`，拿到不跑 Python 也能装",
              ""]
    return "\n".join(lines)


def csv_text() -> str:
    import io
    data, _, _ = rows()
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["path", "role", "items", "unit", "reader", "size",
                "platform", "desc"])
    for r in data:
        w.writerow([r["path"], r["role"], r["items"], r["unit"], r["reader"],
                    r["size"], r["platform"], r["desc"]])
    return buf.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="只校验产物是否过期（CI 用），不写文件")
    args = ap.parse_args()

    if args.check:
        md = render_md()
        # 只校验进版本库的那一份（docs/industry/data-inventory.md）。
        # CSV 落在 out/ 下，而 out/ 被 .gitignore 忽略 —— 干净克隆里它必然不存在，
        # 把它算进 --check 就得到一个「永远过期」的守卫：每次 CI 都红，且红得毫无
        # 信息量，所有人第一件事就是把它关掉。这与脚本开头自己写的那条规矩冲突
        # （过期的清单比没有清单更坏，但永远报过期的校验比两者都坏）。
        # CSV 是导出产物，谁需要谁生成；一致性由生成时同源计算天然保证。
        stale = []
        have = open(DOC, encoding="utf-8").read() if os.path.exists(DOC) else ""
        if have != md:
            stale.append(DOC)
        if stale:
            print("❌ 数据盘存清单已过期（改了数据却没重跑本脚本）：")
            for p in stale:
                print("  - " + os.path.relpath(p, ROOT))
            print("  修法: python3 scripts/gen_data_inventory.py")
            return 1
        print("✅ 数据盘存清单与数据一致")
        return 0

    md, cv = render_md(), csv_text()
    os.makedirs(os.path.dirname(DOC), exist_ok=True)
    os.makedirs(os.path.dirname(CSV_OUT), exist_ok=True)
    with open(DOC, "w", encoding="utf-8") as fh:
        fh.write(md)
    # 不用 newline="" 写：csv 模块默认产 \r\n，而 --check 读回来是 \n 归一化后的文本，
    # 两者永不相等 —— 一个「永远过期」的守卫比没有守卫更坏（所有人都会关掉它）。
    with open(CSV_OUT, "w", encoding="utf-8") as fh:
        fh.write(cv)
    print(f"已生成 → {os.path.relpath(DOC, ROOT)}")
    print(f"已生成 → {os.path.relpath(CSV_OUT, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
