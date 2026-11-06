#!/usr/bin/env python3
"""项目整洁度审计：扫描整个项目，报告结构与卫生问题。

只依赖 Python 标准库。默认只读；--init 和 --fix-gitignore 会写文件。

用法:
    python3 audit.py [项目路径] [--format text|json] [--fail-on error|warn|never] [--all]
    python3 audit.py [项目路径] --init            # 按现有顶层目录生成 .claude/tidy.json 草稿
    python3 audit.py [项目路径] --fix-gitignore   # 把未忽略的依赖 / 生成物 / 垃圾 / 密钥文件补进 .gitignore
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rules import (  # noqa: E402
    CONFIG_PATH, DEPENDENCY_DIRS, JUNK_FILE_GLOBS, KNOWN_DIR_PURPOSES, LOCKFILES, OUTPUT_DIRS, SEVERITY_ORDER,
    SKIP_DIRS, Config, Finding, Project, apply_config, check_path, is_dependency_dir, is_exempt, is_output_dir,
    keep_local_match, load_config, matches_any,
)

EMPTY_OK = {"__init__.py", "py.typed", ".gitkeep", ".keep", ".nojekyll"}
CODE_EXTS = {".py", ".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs", ".sh", ".md", ".vue", ".svelte"}
MAX_HASH_BYTES = 50 * 1024 * 1024
MIN_HASH_BYTES = 64  # 太小的文件（如 "{}"）重复没有意义
TEXT_RULE_LIMIT = 8   # 文本报告里同一规则超过这么多条时折叠，--all 显示全部


def naming_style(stem: str) -> str | None:
    if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)+", stem):
        return "kebab"
    if re.fullmatch(r"[a-z0-9]+(?:_[a-z0-9]+)+", stem):
        return "snake"
    return None


def audit(root: Path, cfg: Config | None = None) -> tuple[list[Finding], dict]:
    root = root.resolve()
    cfg = cfg or load_config(root)
    proj = Project(root)
    findings: list[Finding] = []
    add = findings.append

    def tracked_note(rel: str) -> str:
        return "（已被 git 跟踪）" if rel in proj.tracked else ""

    # ---------- 仓库级 ----------
    if not proj.is_git:
        add(Finding("not-git-repo", "warn", ".", "项目不是 git 仓库，删除和移动无法回滚",
                    "整理前先 git init 并做一次初始提交"))
    if not any((root / n).is_file() for n in ("README.md", "README", "README.rst", "readme.md")):
        add(Finding("missing-readme", "error", ".", "缺少 README", "参考 assets/README.template.md 补充"))
    if not (root / ".gitignore").is_file():
        add(Finding("missing-gitignore", "error", ".", "缺少 .gitignore", "运行 --fix-gitignore 或参考 assets/gitignore/"))
    present_locks = [f for f in LOCKFILES if (root / f).is_file()]
    if len(present_locks) > 1:
        add(Finding("multiple-lockfiles", "warn", ".", f"存在多个包管理器的 lockfile：{', '.join(present_locks)}",
                    "只保留实际使用的包管理器对应的 lockfile"))
    if cfg.error:
        add(Finding("config-invalid", "error", CONFIG_PATH, cfg.error, "修正 JSON 格式和字段类型，见 references/config.md"))
    elif not cfg.exists:
        add(Finding("no-layout", "info", CONFIG_PATH, "项目没有声明目录约定",
                    f"运行 --init 生成 {CONFIG_PATH}，补全每个目录的用途；hooks 会据此引导 AI 把文件放对位置"))

    # ---------- 遍历 ----------
    stats = {"files": 0, "dirs": 0, "skipped_dirs": 0}
    hashes: dict[tuple[int, str], list[str]] = {}
    by_dir_style: dict[tuple[str, str], dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))

    for dirpath, dirnames, filenames in os.walk(root):
        dpath = Path(dirpath)
        rel_dir = dpath.relative_to(root).as_posix()
        rel_dir = "" if rel_dir == "." else rel_dir
        depth = 0 if not rel_dir else rel_dir.count("/") + 1

        all_subdirs = list(dirnames)
        keep_dirs = []
        for d in sorted(dirnames):
            rel = f"{rel_dir}/{d}" if rel_dir else d
            if d in SKIP_DIRS:
                continue
            ignored = proj.is_ignored(rel, True)
            has_tracked = rel in proj.tracked_dirs
            if is_dependency_dir(d):
                if has_tracked:
                    add(Finding("tracked-artifact", "error", rel + "/", "依赖 / 缓存目录中的文件被 git 跟踪",
                                f"git rm -r --cached {rel} 并加入 .gitignore"))
                elif not ignored:
                    add(Finding("artifact-not-ignored", "error", rel + "/", "依赖 / 缓存目录未被 .gitignore 忽略",
                                "加入 .gitignore（可用 --fix-gitignore）"))
                stats["skipped_dirs"] += 1
                continue
            if is_output_dir(root, rel):
                if has_tracked:
                    add(Finding("tracked-artifact", "warn", rel + "/", "疑似生成物目录中的文件被 git 跟踪",
                                "如确为生成物：git rm -r --cached 并加入 .gitignore，在 README 写明生成命令"))
                elif not ignored:
                    add(Finding("artifact-not-ignored", "warn", rel + "/", "疑似生成物目录未被忽略",
                                "如确为生成物，加入 .gitignore（可用 --fix-gitignore）"))
                    stats["skipped_dirs"] += 1
                    continue
            if ignored:
                stats["skipped_dirs"] += 1
                continue
            keep_dirs.append(d)
            findings.extend(check_path(rel, cfg, is_dir=True))
        dirnames[:] = keep_dirs

        if rel_dir:
            stats["dirs"] += 1
            # 只含被忽略文件的目录（本地保留的素材、模型）不算空目录
            real = [f for f in filenames if not matches_any(f, JUNK_FILE_GLOBS)]
            if not all_subdirs and not real:
                add(Finding("empty-dir", "info", rel_dir + "/", "空目录", "不需要就删除"))
            elif not all_subdirs and set(real) <= {".gitkeep", ".keep"}:
                add(Finding("empty-dir", "info", rel_dir + "/", "只有占位文件的目录", "确认是否真的需要"))
        if depth > 7:
            add(Finding("deep-nesting", "info", rel_dir + "/", f"目录层级过深（{depth} 层）", "考虑扁平化"))

        for f in sorted(filenames):
            rel = f"{rel_dir}/{f}" if rel_dir else f
            fpath = dpath / f
            if fpath.is_symlink():
                continue
            ignored = proj.is_ignored(rel, False)
            is_tracked = rel in proj.tracked

            kl = keep_local_match(rel, cfg)
            if kl:
                if is_tracked:
                    add(Finding("keep-local-tracked", "warn", rel, f"按 keepLocal（{kl}）应本地保留、不进 git，但已被跟踪",
                                f"git rm --cached {rel}（保留本地文件），并把该 glob 加进 .gitignore"))
                elif not ignored:
                    add(Finding("keep-local-not-ignored", "warn", rel, f"按 keepLocal（{kl}）应本地保留、不进 git，但未被忽略",
                                "把该 glob 加进 .gitignore（可用 --fix-gitignore）；不要删除文件"))
                continue

            path_findings = check_path(rel, cfg)
            secret = [x for x in path_findings if x.rule == "secret-file"]
            if secret:
                if is_tracked:
                    add(Finding("secret-tracked", "error", rel, "密钥 / 凭据文件被 git 跟踪",
                                "立即轮换密钥；git rm --cached 并加入 .gitignore；必要时清理 git 历史"))
                elif not ignored:
                    add(Finding("secret-not-ignored", "error", rel, "密钥 / 凭据文件未被忽略",
                                "加入 .gitignore（可用 --fix-gitignore），提供 .env.example 代替"))
                continue
            if ignored:
                continue

            stats["files"] += 1
            for x in path_findings:
                if x.rule == "junk-file":
                    x.message += tracked_note(rel)
            findings.extend(path_findings)
            if any(x.rule == "junk-file" for x in path_findings):
                continue

            stem, ext = os.path.splitext(f)
            try:
                size = fpath.stat().st_size
            except OSError:
                continue
            if size == 0 and f not in EMPTY_OK:
                add(Finding("empty-file", "info", rel, "空文件", "不需要就删除"))
            if size > cfg.large_file_mb * 1024 * 1024:
                add(Finding("large-file", "warn", rel, f"大文件 {size / 1024 / 1024:.1f} MB{tracked_note(rel)}",
                            "生成物则忽略；素材考虑 Git LFS 或外部存储，并在 README 说明获取方式"))
            if MIN_HASH_BYTES <= size <= MAX_HASH_BYTES:
                h = hashlib.sha1()
                try:
                    with open(fpath, "rb") as fh:
                        for chunk in iter(lambda: fh.read(1 << 20), b""):
                            h.update(chunk)
                except OSError:
                    pass
                else:
                    hashes.setdefault((size, h.hexdigest()), []).append(rel)
            style = naming_style(stem)
            if style and ext.lower() in CODE_EXTS:
                by_dir_style[(rel_dir, ext.lower())][style].append(f)

    # ---------- 根目录文件数 ----------
    root_files = [p.name for p in root.iterdir() if p.is_file() and not proj.is_ignored(p.name, False)]
    if len(root_files) > cfg.max_root_files:
        add(Finding("root-clutter", "warn", ".", f"根目录有 {len(root_files)} 个文件（建议 ≤ {cfg.max_root_files}）",
                    "非入口级文件移入 src/、scripts/、docs/ 等目录"))

    # ---------- 重复文件 ----------
    # 被 allow 豁免的路径先剔除；同一组目录里的多组重复合并成一条（如连续截帧）
    buckets: dict[tuple[str, ...], list[list[str]]] = defaultdict(list)
    for paths in hashes.values():
        paths = [x for x in paths if not is_exempt(x, cfg, "duplicate-file")]
        if len(paths) > 1:
            dirs = tuple(sorted({x.rsplit("/", 1)[0] if "/" in x else "." for x in paths}))
            buckets[dirs].append(sorted(paths))
    for dirs, groups in buckets.items():
        groups.sort()
        if len(groups) == 1:
            add(Finding("duplicate-file", "info", groups[0][0], f"内容完全相同的文件：{', '.join(groups[0])}",
                        "保留一份并修正引用；交付副本或预期重复可在 allow 中按 duplicate-file 豁免"))
        else:
            sample = "；".join(", ".join(g) for g in groups[:2])
            add(Finding("duplicate-file", "info", dirs[0] + "/",
                        f"{'、'.join(d + '/' for d in dirs)} 中有 {len(groups)} 组内容完全相同的文件，例如：{sample}",
                        "保留一份并修正引用；连续截帧等预期重复可在 allow 中按 duplicate-file 豁免该目录"))

    # ---------- 命名风格混用 ----------
    for (d, ext), styles in by_dir_style.items():
        if len(styles) > 1 and sum(map(len, styles.values())) >= 3:
            detail = "；".join(f"{k}: {', '.join(v[:3])}" for k, v in styles.items())
            add(Finding("mixed-naming", "info", (d or ".") + "/",
                        f"同目录 {ext} 文件混用 kebab-case 与 snake_case（{detail}）", "统一为该语言惯用风格"))

    # ---------- README / layout 是否说明顶层目录 ----------
    readme = next((root / n for n in ("README.md", "readme.md", "README") if (root / n).is_file()), None)
    text = readme.read_text(encoding="utf-8", errors="replace") if readme else ""
    for p in sorted(root.iterdir()):
        if (not p.is_dir() or p.name.startswith(".") or p.name in DEPENDENCY_DIRS
                or proj.is_ignored(p.name, True)):
            continue
        if readme and p.name not in text:
            add(Finding("readme-missing-dir", "info", p.name + "/", "README 未说明这个顶层目录的用途",
                        "在 README「目录结构」中补一句说明"))
    for d in sorted(cfg.layout_dirs):
        if not (root / d).exists():
            add(Finding("layout-missing-dir", "info", d + "/", f"{CONFIG_PATH} 声明了该目录，但它不存在",
                        "目录已废弃就从 layout 中移除"))

    # 去重（同一顶层目录下的多个文件会重复报告 undeclared-dir）
    seen, unique = set(), []
    for f in apply_config(findings, cfg):
        if (f.rule, f.path) not in seen:
            seen.add((f.rule, f.path))
            unique.append(f)
    unique.sort(key=lambda x: (SEVERITY_ORDER[x.severity], x.rule, x.path))
    summary = {
        "root": str(root),
        "git": proj.is_git,
        "config": cfg.exists,
        "scanned_files": stats["files"],
        "scanned_dirs": stats["dirs"],
        "skipped_dirs": stats["skipped_dirs"],
        "counts": {s: sum(1 for f in unique if f.severity == s) for s in SEVERITY_ORDER},
    }
    return unique, summary


def init_config(root: Path) -> Path:
    """按现有顶层目录生成 .claude/tidy.json 草稿。已存在时不覆盖。"""
    target = root / CONFIG_PATH
    if target.exists():
        raise FileExistsError(target)
    proj = Project(root)
    layout = {}
    for p in sorted(root.iterdir()):
        if (p.is_dir() and p.name not in SKIP_DIRS and p.name not in DEPENDENCY_DIRS
                and p.name not in OUTPUT_DIRS and not p.name.startswith(".")
                and not proj.is_ignored(p.name, True)):
            layout[p.name + "/"] = KNOWN_DIR_PURPOSES.get(p.name, "TODO: 说明这个目录放什么")
    data = {"layout": layout, "allow": [], "rootAllow": [], "disable": []}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def fix_gitignore(root: Path, findings: list[Finding]) -> list[str]:
    """把未忽略（且未被跟踪）的依赖 / 生成物 / 垃圾 / 密钥文件补进 .gitignore。返回新增的条目。"""
    entries: list[str] = []
    for f in findings:
        if f.rule == "artifact-not-ignored":
            entries.append(f.path.rstrip("/").rsplit("/", 1)[-1] + "/")
        elif f.rule == "secret-not-ignored":
            name = f.path.rsplit("/", 1)[-1]
            entries.append(".env*\n!.env.example" if name.startswith(".env") else name)
        elif f.rule == "junk-file" and "已被 git 跟踪" not in f.message:
            name = f.path.rsplit("/", 1)[-1]
            ext = os.path.splitext(name)[1]
            entries.append(f"*{ext}" if ext and not name.startswith(".") else name)
        elif f.rule == "keep-local-not-ignored":
            m = re.search(r"keepLocal（(.+?)）", f.message)
            if m:
                entries.append(m.group(1))
    gi = root / ".gitignore"
    existing = gi.read_text(encoding="utf-8").splitlines() if gi.is_file() else []
    new = []
    for e in dict.fromkeys(entries):
        if all(line not in existing for line in e.splitlines()):
            new.append(e)
    if new:
        with open(gi, "a", encoding="utf-8") as fh:
            if existing and existing[-1].strip():
                fh.write("\n")
            fh.write("# added by tidy\n" + "\n".join(new) + "\n")
    return new


def render_text(findings: list[Finding], summary: dict, show_all: bool = False) -> str:
    icons = {"error": "✖ ERROR", "warn": "▲ WARN ", "info": "● INFO "}
    lines = [
        f"项目整洁度审计：{summary['root']}",
        f"git 仓库：{'是' if summary['git'] else '否'}  目录约定：{'有' if summary['config'] else '无'}  "
        f"扫描文件 {summary['scanned_files']} 个，目录 {summary['scanned_dirs']} 个"
        f"（跳过已忽略 / 依赖目录 {summary['skipped_dirs']} 个）",
        "",
    ]
    if not findings:
        lines.append("没有发现问题。")
        return "\n".join(lines)
    by_rule: dict[str, list[Finding]] = {}
    for f in findings:
        by_rule.setdefault(f.rule, []).append(f)
    for rule, items in by_rule.items():
        lines.append(f"[{rule}]" + (f"  共 {len(items)} 条" if len(items) > 1 else ""))
        shown = items if show_all or len(items) <= TEXT_RULE_LIMIT else items[:5]
        for f in shown:
            lines.append(f"  {icons[f.severity]}  {f.path}  —  {f.message}")
            if f.suggestion and (f is shown[0] or f.suggestion != shown[0].suggestion):
                lines.append(f"           → {f.suggestion}")
        if len(shown) < len(items):
            lines.append(f"  ……另有 {len(items) - len(shown)} 条同类（--all 或 --format json 查看全部；"
                         f"属于预期情况可在 allow 中按 {rule} 豁免对应目录）")
    c = summary["counts"]
    lines += ["", f"合计：{c['error']} error，{c['warn']} warn，{c['info']} info",
              "提示：脚本是启发式检查。删除或移动前用 refs.py 确认文件没有被引用。"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="项目整洁度审计")
    ap.add_argument("path", nargs="?", default=".", help="项目根目录，默认当前目录")
    ap.add_argument("--format", choices=["text", "json"], default="text")
    ap.add_argument("--fail-on", choices=["error", "warn", "never"], default="never",
                    help="达到该级别时以非零状态退出（用于 CI）")
    ap.add_argument("--all", action="store_true", help="文本报告不折叠同类问题")
    ap.add_argument("--init", action="store_true", help=f"生成 {CONFIG_PATH} 草稿")
    ap.add_argument("--fix-gitignore", action="store_true", help="把应忽略的文件补进 .gitignore")
    args = ap.parse_args(argv)

    root = Path(args.path).resolve()
    if not root.is_dir():
        print(f"不是目录：{root}", file=sys.stderr)
        return 2

    if args.init:
        try:
            target = init_config(root)
        except FileExistsError as e:
            print(f"已存在，不覆盖：{e}", file=sys.stderr)
            return 1
        print(f"已生成 {target}，请补全每个目录的用途（TODO 项），并同步 README「目录结构」。")
        return 0

    findings, summary = audit(root)
    if args.fix_gitignore:
        added = fix_gitignore(root, findings)
        if added:
            print("已追加到 .gitignore：")
            for e in added:
                for line in e.splitlines():
                    print(f"  {line}")
        else:
            print(".gitignore 无需修改。")
        tracked = [f for f in findings if f.rule in ("tracked-artifact", "secret-tracked", "keep-local-tracked")
                   or (f.rule == "junk-file" and "已被 git 跟踪" in f.message)]
        if tracked:
            print("以下内容已被 git 跟踪，需手动 git rm --cached（密钥还需轮换）：")
            for f in tracked:
                print(f"  {f.path}")
        return 0

    if args.format == "json":
        print(json.dumps({"summary": summary, "findings": [asdict(f) for f in findings]},
                         ensure_ascii=False, indent=2))
    else:
        print(render_text(findings, summary, args.all))

    if args.fail_on == "never":
        return 0
    threshold = SEVERITY_ORDER[args.fail_on]
    return 1 if any(SEVERITY_ORDER[f.severity] <= threshold for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
