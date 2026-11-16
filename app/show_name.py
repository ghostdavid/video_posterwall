"""从专辑文件夹名解析剧集名。

规则：取文件夹名中第一对【】之间的文本；连续多个【 或 】视为同一对括号的装饰。
    【【aa】】   -> aa
    【bb】【cc】 -> bb
    【aa】       -> aa
找不到【】时，退化为使用整个文件夹名（去掉首尾括号与空白）。
"""
from __future__ import annotations

import re

# 【+ 吸收连续左括号，】+ 吸收连续右括号；(.*?) 取中间最短有效文本
_BRACKET_RE = re.compile(r"【+(.*?)】+", re.S)


def parse_show_name(folder_name: str) -> tuple[str, str]:
    """返回 (剧集名, 来源说明)。"""
    raw = folder_name or ""
    match = _BRACKET_RE.search(raw)
    if match:
        name = match.group(1).strip().lstrip("【").rstrip("】").strip()
        name = name.strip("【】").strip()
        if name:
            return name, "取自文件夹名中第一对【】之间的文本"
    fallback = raw.strip().strip("【】").strip()
    if not fallback:
        fallback = "Untitled"
    return fallback, "文件夹名中没有【】，已使用整个文件夹名"


def describe_examples() -> str:
    return "【【aa】】 → aa；【bb】【cc】 → bb；【剧集名】1080P → 剧集名"
