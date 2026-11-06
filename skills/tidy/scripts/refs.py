#!/usr/bin/env python3
"""查找文件在项目中被引用的位置，用于判断"这个文件还有没有用"、移动后要改哪里。

用法:
    python3 refs.py <项目路径> <文件路径> [<文件路径> ...] [--format text|json]

对每个目标文件，在项目里所有未被忽略的文本文件中搜索：
  - 相对路径（去掉 src/、public/ 等常见前缀后的路径也算）    强引用
  - 文件名（含扩展名）                                       强引用
  - 不含扩展名的模块名（如 import ./Title）                   弱引用，可能误报

搜不到引用 ≠ 一定没用：动态拼接的路径、glob 加载、框架约定加载都搜不到，需要人工确认。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rules import SECRET_ALLOW, SECRET_FILE_GLOBS, Project, iter_files, matches_any  # noqa: E402

MAX_BYTES = 1024 * 1024
STRIP_PREFIXES = ("src/", "public/", "static/", "assets/", "app/", "lib/")
# 这些模块名太通用，作为弱引用没有意义
GENERIC_STEMS = {"index", "main", "app", "utils", "util", "helpers", "types", "config", "constants", "init", "__init__"}
# 框架 / 工具按约定加载、不会被显式引用的文件
CONVENTION_FILES = {
    "index.ts", "index.tsx", "index.js", "main.py", "__init__.py", "conftest.py", "setup.py", "manage.py",
    "Root.tsx", "page.tsx", "layout.tsx", "route.ts", "middleware.ts", "remotion.config.ts",
}


def tokens_for(rel: str) -> list[tuple[str, str]]:
    name = rel.rsplit("/", 1)[-1]
    stem = os.path.splitext(name)[0]
    toks = [(rel, "strong")]
    for pre in STRIP_PREFIXES:
        if rel.startswith(pre):
            toks.append((rel[len(pre):], "strong"))
    toks.append((name, "strong"))
    if len(stem) >= 3 and stem.lower() not in GENERIC_STEMS and stem != name:
        toks.append((stem, "weak"))
    return list(dict.fromkeys(toks))


def find_refs(root: Path, targets: list[str]) -> dict[str, dict]:
    proj = Project(root)
    files = list(iter_files(root, proj))
    texts: dict[str, list[str]] = {}
    for rel in files:
        name = rel.rsplit("/", 1)[-1]
        if matches_any(name, SECRET_FILE_GLOBS) and name not in SECRET_ALLOW:
            continue  # 不读取密钥文件，避免把密钥内容带进输出
        p = root / rel
        try:
            if p.stat().st_size > MAX_BYTES:
                continue
            raw = p.read_bytes()
        except OSError:
            continue
        if b"\0" in raw[:8192]:
            continue
        texts[rel] = raw.decode("utf-8", "replace").splitlines()

    result = {}
    for target in targets:
        rel = Path(target).resolve().relative_to(root).as_posix() if os.path.isabs(target) else target.removeprefix("./")
        toks = tokens_for(rel)
        hits = []
        for src, lines in texts.items():
            if src == rel:
                continue
            for i, line in enumerate(lines, 1):
                for tok, strength in toks:
                    if strength == "strong":
                        m = re.search(re.escape(tok), line)
                    else:
                        m = re.search(r"(?<![\w-])" + re.escape(tok) + r"(?![\w-])", line)
                        # 相对导入 ./Root、../lib/Root 这类以路径段结尾的引用视为强引用
                        if m and re.search(r"/" + re.escape(tok) + r"(\.\w+)?[\"'`]", line):
                            strength = "strong"
                    if m:
                        hits.append({"file": src, "line": i, "strength": strength, "token": tok,
                                     "text": line.strip()[:160]})
                        break
        strong = [h for h in hits if h["strength"] == "strong"]
        name = rel.rsplit("/", 1)[-1]
        if strong:
            verdict = "in-use"
        elif name in CONVENTION_FILES:
            verdict = "convention"
        elif hits:
            verdict = "maybe"
        else:
            verdict = "unreferenced"
        result[rel] = {"verdict": verdict, "exists": (root / rel).exists(), "hits": hits}
    return result


VERDICT_TEXT = {
    "in-use": "在用：有明确引用",
    "convention": "可能由框架 / 工具按约定加载，不要仅凭无引用就删除",
    "maybe": "只有模块名的弱匹配，需要人工确认",
    "unreferenced": "未找到引用（注意动态路径、glob 加载、外部调用）",
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="查找文件引用")
    ap.add_argument("root")
    ap.add_argument("targets", nargs="+")
    ap.add_argument("--format", choices=["text", "json"], default="text")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    res = find_refs(root, args.targets)
    if args.format == "json":
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    for rel, r in res.items():
        print(f"{rel}  [{r['verdict']}] {VERDICT_TEXT[r['verdict']]}{'' if r['exists'] else '（文件不存在）'}")
        for h in r["hits"][:30]:
            mark = "" if h["strength"] == "strong" else "（弱）"
            print(f"  {h['file']}:{h['line']}{mark}  {h['text']}")
        if len(r["hits"]) > 30:
            print(f"  ……另有 {len(r['hits']) - 30} 处")
    return 0


if __name__ == "__main__":
    sys.exit(main())
