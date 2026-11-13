"""带 !include 的 YAML 加载（目录化词表用）

为什么：一个文件装全部行业类，条目一多就变成"一堆同义词的流水账"，
没人能管，也没法分工。词表按域拆成目录后，需要能拼装。

只支持两种写法，够用且不会变成第二套编程语言：

    whole:  !include upstream.yaml          # 整文件并入（路径相对当前文件）
    merge:  !include [a.yaml, b.yaml]       # 逐文件并入并浅合并成一个 mapping

刻意不做变量替换、不做条件、不做跨文件覆盖优先级 —— 那是数据库和模板引擎的活。

实现注意（踩过的坑）：!include 必须**独立**解析被包含文件，不能把子文档的值
塞回父 loader 的构造流程。PyYAML 的 construct_object 以「节点对象」为 key 做缓存，
父子文档里 value 相同的标量节点会被判成同一个对象，于是
`classes: !include x.yaml`（x.yaml 里也是 `classes: ...`）会解析成
`{classes: {classes: ...}}` 这种错位嵌套。所以这里用 compose 拿节点树，
映射合并自己在 Python 里做，两边缓存完全隔离。
"""
from __future__ import annotations

import os
from typing import Any, Optional

import yaml


class IncludeError(Exception):
    """!include 解析失败（缺文件、循环引用、非 mapping 目标）。"""


def _scalar(node: yaml.Node) -> str:
    if not isinstance(node, yaml.ScalarNode):
        raise IncludeError("!include 只接受文件路径或路径列表")
    return str(node.value).strip()


def _build(node: yaml.Node, base: str, seen: tuple) -> Any:
    """把节点树转成 Python 对象，!include 在这一层展开。"""
    if node.tag == "!include":
        items = node.value if isinstance(node, yaml.SequenceNode) else [node]
        # 各域文件都以同一个顶层 key 开头（classes:），被包含文件里那层 key
        # 重复的是父级已经写了的那层，一并带回来就会多一层嵌套，
        # 所以这里逐文件取出「根里唯一的那个 key 的值」再合并。
        merged: dict = {}
        for item in items:
            data = _load_file(os.path.join(base, _scalar(item)), seen)
            if not isinstance(data, dict):
                raise IncludeError("!include 目标必须是 mapping")
            if len(data) == 1:
                (_, only), = data.items()
                if isinstance(only, dict):
                    data = only
            merged.update(data)
        return merged

    if isinstance(node, yaml.ScalarNode):
        tag = node.tag
        if tag.endswith(":null"):
            return None
        if tag.endswith(":bool"):
            return str(node.value).lower() in ("true", "yes", "on")
        if tag.endswith(":int"):
            return int(node.value)
        if tag.endswith(":float"):
            return float(node.value)
        return str(node.value)

    if isinstance(node, yaml.SequenceNode):
        return [_build(item, base, seen) for item in node.value]

    return {_build(k, base, seen): _build(v, base, seen) for k, v in node.value}


def _load_file(path: str, seen: tuple) -> Any:
    real = os.path.abspath(path)
    if real in seen:
        raise IncludeError(f"!include 循环引用：{real}")
    if not os.path.exists(real):
        raise IncludeError(f"!include 目标不存在：{real}")
    with open(real, "r", encoding="utf-8") as fh:
        node = yaml.compose(fh)
    if node is None:
        return None
    return _build(node, os.path.dirname(real), seen + (real,))


def load(path: str) -> Optional[dict]:
    """读一个可能含 !include 的 YAML；文件不存在返回 None。"""
    if not path or not os.path.exists(path):
        return None
    return _load_file(path, ())


def load_dir(path: str) -> dict:
    """读目录下所有 *.yaml（跳过 _ 开头的模板），浅合并成一个 mapping。

    目录化是为了让词表能按域拆文件、按文件分工，同时保留"一处声明、多处引用"。
    """
    merged: dict = {}
    if not os.path.isdir(path):
        return merged
    for name in sorted(os.listdir(path)):
        if not name.endswith(".yaml") or name.startswith("_"):
            continue
        data = load(os.path.join(path, name))
        if isinstance(data, dict):
            for key, value in data.items():
                if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
                    merged[key].update(value)
                else:
                    merged[key] = value
    return merged
