"""M11 职业视角轴 · 原子化岗位 + 软归属（occupation_axis）

用户拍板的模型，一句话：**岗位原子化，归属模糊化，分类是筛选器不是户籍。**

    occupation  —— 原子单元。唯一编号（OCC-000001）+ 稳定 slug。
                   **没有 unit_id，没有"我在哪个分区"这种字段。**
                   归属变了不需要改职业记录，只改下面这张表。
    profile     —— 一个职业在一根轴上的一个视角取值（职业内去重）。
                   一个职业可以同时属于任意多个分区，权重不必相加为 100：
                   0.6 + 0.5 不是错误，是"两件活都真干"。
    membership  —— 由 profile 展开出来的**边**：occupation × partition × axis。
                   只读派生结果，不手写。分区不存成员清单，职业不存归属字段，
                   所以两边永远不会分叉。

为什么要拆成 profile + membership 两张表：

1. **硬归属会丢信息。** 单值 unit_id 写着"字幕翻译属于翻译本地化"，
   就再也表达不了"同一个人也接视频影视的字幕活"。改分区名/拆分区时，
   挂在单一字段上的职业整批跟着漂移或漏掉。
2. **分类维度是模糊的，权重才是诚实的表达。** 用 0.7/0.2/0.1 说"主要干这个、
   顺带干那个"，比逼着数据选一个"正确归属"更接近事实；也允许按需只取
   weight >= 阈值 的子集，做筛选而不是判归属。
3. **多根轴互不干扰。** 职业/行业/税收/产出各有自己的取值空间，加一根轴
   不会动另一根，也不会动职业本身。

硬不变量（validate 会报）：
- 同一 (occupation, partition, axis) 只能有一条——两条就是"同一件事说了两遍"；
- weight 必须落在 (0, 1]，0 或负数没有意义（不想归属就别写这条边）；
- partition 必须是已知分区（悬空边）；
- 单根轴上的权重和只在是"互斥分组"时才该等于 1；不要求，也不因为不等于 1 报错。
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional

import yaml

# 合法轴：与 industry_db.AXES 对齐，但这里是"职业能挂到哪些视角"，语义独立
AXES = ("occupation", "industry", "tax", "output")
# 轴内视角的缺省值：不写 profile 就按单值字段推出来的那一条
DEFAULT_WEIGHT = 1.0
# 一个职业在同一根轴上"主要归谁"的权重门槛（仅用于展示 primary，不参与校验）
PRIMARY_WEIGHT = 0.5

_ID_RE = re.compile(r"^OCC-(\d{6,})$")


def format_code(seq: int) -> str:
    """序号 → 唯一岗位编号（OCC-000001）。位数只增不减，可排序、可对齐外部表。"""
    return f"OCC-{int(seq):06d}"


def parse_code(code: str) -> Optional[int]:
    """唯一岗位编号 → 序号；格式不对返回 None（别猜，猜错就会撞号）。"""
    m = _ID_RE.match((code or "").strip())
    return int(m.group(1)) if m else None


class OccupationAxis:
    """职业的软归属视图：按轴/分区/权重查职业，不提供"唯一归属"这种接口。"""

    def __init__(self, occupations: List[dict], partitions: List[dict],
                 memberships: Optional[List[dict]] = None):
        self.occupations = occupations or []
        self.partitions = partitions or []
        # profile 是写入形态（一个人一条，自带多轴），memberships 是展开形态。
        # 两者同源：给了 memberships 就不再展开 profile，避免同一件事算两遍。
        self._explicit_memberships = memberships or []
        self._occ_by_slug: Dict[str, dict] = {
            o.get("id", ""): o for o in self.occupations if o.get("id")}
        self._occ_by_code: Dict[str, dict] = {
            o.get("code", ""): o for o in self.occupations if o.get("code")}
        self.memberships: List[dict] = self._expand()
        self._index()

    # ------------------------------------------------------------ 构建
    def _expand(self) -> List[dict]:
        if self._explicit_memberships:
            return [dict(m) for m in self._explicit_memberships]
        edges: List[dict] = []
        for o in self.occupations:
            for m in self.profile_of(o):
                edges.append(m)
        return edges

    def profile_of(self, occupation: dict) -> List[dict]:
        """职业的归属 profile（边列表）。

        显式 ``profile`` 优先；没有就由老字段单值推一条（``legacy: true``）：
        unit_id 既可能是分区 id 也可能是单元 id，这里原样当分区 key ——
        单元和分区同名的数据不需要特判，不同名的由 validate 报悬空。

        单值字段推出来的边只说明"这份数据以前只有这一个说法"，
        **不代表职业只能属于这里**，加 profile 就是加别的说法。
        """
        occ_id = occupation.get("id", "")
        rows = occupation.get("profile")
        edges: List[dict] = []
        if isinstance(rows, list) and rows:
            for row in rows:
                if not isinstance(row, dict):
                    continue
                part = row.get("partition") or row.get("unit_id") or ""
                if not part:
                    continue
                edges.append({
                    "occupation": occ_id,
                    "partition": part,
                    "axis": row.get("axis") or "occupation",
                    "weight": row.get("weight", DEFAULT_WEIGHT),
                    "unit_role": row.get("unit_role") or "",
                    "note": row.get("note") or "",
                    "legacy": False,
                })
            return edges
        part = occupation.get("unit_id") or ""
        if part:
            edges.append({
                "occupation": occ_id,
                "partition": part,
                "axis": occupation.get("axis") or "occupation",
                "weight": DEFAULT_WEIGHT,
                "unit_role": occupation.get("unit_role") or "",
                "note": "",
                "legacy": True,
            })
        return edges

    def _index(self) -> None:
        self._by_part: Dict[str, List[dict]] = {}
        self._by_occ: Dict[str, List[dict]] = {}
        self._by_axis: Dict[str, List[dict]] = {}
        for m in self.memberships:
            self._by_part.setdefault(m.get("partition", ""), []).append(m)
            self._by_occ.setdefault(m.get("occupation", ""), []).append(m)
            self._by_axis.setdefault(m.get("axis", ""), []).append(m)

    def refresh(self, memberships: Optional[List[dict]] = None) -> None:
        """重建视图。

        给了 ``memberships`` 就用它（外部显式改动过边，比如删边/改权重）；
        不给就按当前 occupations/partitions 重新派生。
        """
        if memberships is not None:
            self._explicit_memberships = [dict(m) for m in memberships]
            self.memberships = self._explicit_memberships
        else:
            self.memberships = self._expand()
        self._index()

    # ------------------------------------------------------------ 查询
    def of_occupation(self, occ_id: str, axis: str = "",
                      min_weight: float = 0.0) -> List[dict]:
        """这个岗位落在哪些视角里（不是"它属于哪个"）。"""
        rows = self._by_occ.get(occ_id, [])
        return self._filter(rows, axis, min_weight)

    def of_partition(self, partition: str, axis: str = "",
                     min_weight: float = 0.0) -> List[dict]:
        rows = self._by_part.get(partition, [])
        return self._filter(rows, axis, min_weight)

    def occupations_of(self, partition: str, axis: str = "",
                       min_weight: float = 0.0) -> List[dict]:
        """某视角下的职业（按权重降序；权重相同按 id，保证输出稳定）。"""
        edges = sorted(self.of_partition(partition, axis, min_weight),
                       key=lambda m: (-self._weight(m), m.get("occupation", "")))
        return [self._occ_by_slug[m["occupation"]] for m in edges
                if m.get("occupation") in self._occ_by_slug]

    def of_axis(self, axis: str) -> List[dict]:
        return list(self._by_axis.get(axis, []))

    def filter(self, partition: str = "", axis: str = "",
               provider: str = "", billing: str = "", access: str = "",
               deliverable: str = "", min_weight: float = 0.0,
               baseline_only: bool = False) -> List[dict]:
        """筛选器语义：条件之间是"与"，同一条件多值由调用方多次调用。

        这是本模型的核心用法——想从哪个角度看就从哪个角度筛，
        不需要先决定职业"归"到哪里。
        """
        if partition:
            cand = {m["occupation"] for m in self.of_partition(
                partition, axis, min_weight)}
        else:
            cand = {m.get("occupation", "") for m in self._filter(
                self.memberships, axis, min_weight)}
        out = []
        for occ_id in cand:
            o = self._occ_by_slug.get(occ_id)
            if not o:
                continue
            if provider and o.get("provider") != provider:
                continue
            if billing and o.get("billing") != billing:
                continue
            if deliverable and o.get("deliverable") != deliverable:
                continue
            if access and (o.get("access") or "paid_direct") != access:
                continue
            if baseline_only and not o.get("baseline_occupation"):
                continue
            out.append(o)
        return sorted(out, key=lambda o: o.get("code") or o.get("id", ""))

    def primary_of(self, occ_id: str, axis: str = "occupation") -> List[dict]:
        """该轴上的主要归属（权重 >= PRIMARY_WEIGHT）。可能为空，也可能不止一个。"""
        return self.of_occupation(occ_id, axis, PRIMARY_WEIGHT)

    def free_occupations(self) -> List[dict]:
        """没有被任何视角引用的职业：不是缺口，是"还没被任何聚类看上"。

        它们照样在册、照样进统计——原子岗位不靠归属活着。
        """
        used = {m.get("occupation", "") for m in self.memberships}
        return [o for o in self.occupations if o.get("id") not in used]

    def unassigned_occupations(self) -> List[dict]:
        """老字段 unit_id 为空的职业（保留语义，供旧命令/旧脚本继续用）。"""
        return [o for o in self.occupations if not o.get("unit_id")]

    def axis_mix(self, partition: str = "") -> Dict[str, int]:
        """某分区（或全库）在各轴上各有几条边，用来看"这个分区是几维的"。"""
        rows = self.of_partition(partition) if partition else self.memberships
        mix = {a: 0 for a in AXES}
        for m in rows:
            a = m.get("axis") or ""
            mix[a] = mix.get(a, 0) + 1
        return mix

    # ------------------------------------------------------------ 校验
    def validate(self) -> List[str]:
        problems: List[str] = []

        # A. 唯一编号：空、重复、格式不对、与序号不匹配
        seen_code: Dict[str, List[int]] = {}
        seen_slug: Dict[str, List[int]] = {}
        for i, o in enumerate(self.occupations, 1):
            code = (o.get("code") or "").strip()
            slug = (o.get("id") or "").strip()
            if not code:
                problems.append(
                    f"职业 {slug or f'第 {i} 条'} 缺少唯一编号 code"
                    f"（原子岗位的身份证，缺了就无法跨表对齐）")
            elif parse_code(code) is None:
                problems.append(f"职业 {slug} 的 code={code!r} 不符合 OCC-数字 格式")
            seen_code.setdefault(code, []).append(i)
            seen_slug.setdefault(slug, []).append(i)
        for code, pos in seen_code.items():
            if code and len(pos) > 1:
                problems.append(
                    f"职业编号重复: {code} 出现 {len(pos)} 次"
                    f"（第 {'、'.join(str(x) for x in pos)} 条）—— 唯一编号必须唯一")
        for slug, pos in seen_slug.items():
            if slug and len(pos) > 1:
                problems.append(
                    f"职业 slug 重复: {slug} 出现 {len(pos)} 次"
                    f"（第 {'、'.join(str(x) for x in pos)} 条）")

        # B. 软归属：边只能指向已知分区，权重合法，同一条边不重复
        known = {p.get("id", "") for p in self.partitions if p.get("id")}
        seen_edge: Dict[tuple, int] = {}
        for i, m in enumerate(self.memberships, 1):
            occ_id = m.get("occupation", "")
            part = m.get("partition", "")
            axis = m.get("axis") or ""
            w = m.get("weight", DEFAULT_WEIGHT)
            if occ_id not in self._occ_by_slug:
                problems.append(f"归属边指向不存在的职业: {occ_id}（第 {i} 条）")
            if part not in known:
                problems.append(
                    f"职业 {occ_id} 的归属指向不存在的分区 {part}（第 {i} 条）")
            if axis not in AXES:
                problems.append(
                    f"职业 {occ_id} 的归属轴 {axis!r} 不在 {list(AXES)} 中"
                    f"（写错等于这条边在任何视角下都查不到）")
            try:
                wf = float(w)
            except (TypeError, ValueError):
                problems.append(f"职业 {occ_id} 在分区 {part} 的 weight={w!r} 不是数值")
                wf = DEFAULT_WEIGHT
            if not (0 < wf <= 1):
                problems.append(
                    f"职业 {occ_id} 在分区 {part} 的 weight={w} 超出 (0, 1]"
                    f"（不想归属就别写这条边，写 0 只会制造噪音）")
            key = (occ_id, part, axis)
            if key in seen_edge:
                problems.append(
                    f"职业 {occ_id} 在分区 {part} 轴 {axis} 上有重复归属"
                    f"（第 {seen_edge[key]} 条与第 {i} 条）—— 同一件事说了两遍")
            else:
                seen_edge[key] = i

        # C. 编号与序号：code 与职业序号必须一一对应，防止手改编号后错位
        for i, o in enumerate(self.occupations, 1):
            code = (o.get("code") or "").strip()
            seq = parse_code(code)
            if seq is not None and seq != i:
                problems.append(
                    f"职业 {o.get('id')} 的编号 {code} 与登记序号 {i} 不一致"
                    f"（编号一旦分配就不该随增删漂移，请用 scripts 里的一致性修复）")
        return problems

    # ------------------------------------------------------------ 内部
    @staticmethod
    def _weight(m: dict) -> float:
        try:
            return float(m.get("weight", DEFAULT_WEIGHT))
        except (TypeError, ValueError):
            return DEFAULT_WEIGHT

    def _filter(self, rows: Iterable[dict], axis: str,
                min_weight: float) -> List[dict]:
        out = []
        for m in rows:
            if axis and m.get("axis") != axis:
                continue
            if min_weight and self._weight(m) < min_weight:
                continue
            out.append(m)
        return out
