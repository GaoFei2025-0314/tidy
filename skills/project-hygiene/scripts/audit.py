#!/usr/bin/env python3
"""项目整洁度审计：扫描项目目录，报告结构与卫生问题。

只依赖 Python 标准库。脚本只读，不会修改任何文件。

用法:
    python3 audit.py [项目路径] [--format text|json] [--fail-on error|warn|never]
                     [--max-root-files N] [--large-mb N]
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

SEVERITY_ORDER = {"error": 0, "warn": 1, "info": 2}

# 依赖 / 缓存目录：出现即应被忽略，扫描时不进入
DEPENDENCY_DIRS = {
    "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".ipynb_checkpoints", ".parcel-cache", ".turbo", ".next", ".nuxt",
    ".cache", ".tox", ".gradle",
}
# 常见生成物目录：通常应被忽略，但少数项目里是源码，因此只给 warn
OUTPUT_DIRS = {"build", "dist", "out", "coverage", "htmlcov", "target", "renders"}
# 永不扫描
SKIP_DIRS = {".git", ".hg", ".svn"}

JUNK_FILE_GLOBS = [
    ".DS_Store", "Thumbs.db", "desktop.ini", "*.log", "*.tmp", "*.swp", "*~",
    "*.bak", "*.orig", "*.pyc", "*.pyo",
]
SECRET_FILE_GLOBS = [
    ".env", ".env.*", "*.pem", "*.key", "id_rsa", "id_ed25519", "credentials.json",
    "service-account*.json", "*.p12", "*.keystore",
]
SECRET_ALLOW = {".env.example", ".env.sample", ".env.template"}

# 版本 / 副本后缀：foo_v2, foo-new, foo.backup, foo copy, foo (1), 副本, 最终版
VERSION_SUFFIX_RE = re.compile(
    r"(?:[_\-. ](?:v\d+|new|old|backup|bak|copy|final|tmp|temp|orig|draft\d*|fixed|updated)"
    r"|\s\(\d+\)|副本|最终版?|新版|旧版|备份)$",
    re.IGNORECASE,
)
# AI 常生成的任务报告类文档
REPORT_DOC_RE = re.compile(
    r"(SUMMARY|IMPLEMENTATION|REPORT|PROGRESS|CHANGES_|_CHANGES|FIX(ES)?_|_FIX|"
    r"COMPLETE|STATUS|MIGRATION_NOTES|WALKTHROUGH|总结|报告|进度)",
    re.IGNORECASE,
)
STANDARD_DOCS = {
    "readme", "changelog", "license", "licence", "contributing", "code_of_conduct",
    "security", "agents", "claude", "gemini", "notice", "authors", "support",
}
# 临时 / 调试脚本名
SCRATCH_NAME_RE = re.compile(
    r"^(test\d*|tmp\d*|temp\d*|scratch\w*|debug\w*|untitled\w*|foo|bar|demo\d*|"
    r"playground|try\w*|check_\w+|a+|xxx)\.(py|js|ts|mjs|cjs|sh|txt|md|json)$",
    re.IGNORECASE,
)
# 根目录允许的文件
ROOT_ALLOWED_GLOBS = [
    "README*", "LICENSE*", "LICENCE*", "CHANGELOG*", "CONTRIBUTING*", "CODE_OF_CONDUCT*",
    "SECURITY*", "AGENTS.md", "CLAUDE.md", "GEMINI.md", "NOTICE*", "AUTHORS*",
    "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "pnpm-workspace.yaml",
    "bun.lockb", "bun.lock", ".npmrc", ".nvmrc", ".node-version", "pyproject.toml",
    "requirements*.txt", "uv.lock", "poetry.lock", "Pipfile", "Pipfile.lock", "setup.py",
    "setup.cfg", ".python-version", "Cargo.toml", "Cargo.lock", "go.mod", "go.sum",
    "tsconfig*.json", "jsconfig.json", "*.config.js", "*.config.ts", "*.config.mjs",
    "*.config.cjs", "*.config.json", ".eslintrc*", "eslint.config.*", ".prettierrc*",
    ".prettierignore", ".editorconfig", ".gitignore", ".gitattributes", ".dockerignore",
    "Dockerfile*", "docker-compose*.yml", "compose*.yml", "Makefile", "justfile",
    ".env.example", ".env.sample", "biome.json", "turbo.json", "nx.json", "vercel.json",
    "netlify.toml", ".pre-commit-config.yaml", "ruff.toml", "mypy.ini", "pytest.ini",
    "tox.ini", ".flake8", "renovate.json", ".releaserc*", "lerna.json", "deno.json",
    "components.json", "index.html", ".env", ".DS_Store",
]
LOCKFILES = ["package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb", "bun.lock"]
EMPTY_OK = {"__init__.py", "py.typed", ".gitkeep", ".keep", ".nojekyll"}
CODE_EXTS = {".py", ".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs", ".sh", ".md", ".vue", ".svelte"}
PORTABLE_NAME_RE = re.compile(r"^[A-Za-z0-9._\-@+]+$")
MAX_HASH_BYTES = 50 * 1024 * 1024
MIN_HASH_BYTES = 64  # 太小的文件（如 "{}"）重复没有意义


@dataclass
class Finding:
    rule: str
    severity: str
    path: str
    message: str
    suggestion: str = ""


class Project:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.is_git = self._git(["rev-parse", "--is-inside-work-tree"]) == "true"
        self.tracked: set[str] = set()
        self.tracked_dirs: set[str] = set()
        self.ignored: set[str] = set()
        self.gitignore_patterns: list[str] = []
        if self.is_git:
            self.tracked = set(self._git_z(["ls-files", "-z"]))
            for t in self.tracked:
                parts = t.split("/")[:-1]
                for i in range(1, len(parts) + 1):
                    self.tracked_dirs.add("/".join(parts[:i]))
            self.ignored = set(
                self._git_z(["ls-files", "-z", "--others", "--ignored", "--exclude-standard", "--directory"])
            )
        else:
            gi = self.root / ".gitignore"
            if gi.is_file():
                for line in gi.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if line and not line.startswith(("#", "!")):
                        self.gitignore_patterns.append(line)

    def _git(self, args: list[str]) -> str:
        try:
            out = subprocess.run(
                ["git", "-C", str(self.root), *args], capture_output=True, text=True, check=True
            )
            return out.stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            return ""

    def _git_z(self, args: list[str]) -> list[str]:
        try:
            out = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            return []
        return [p for p in out.stdout.decode("utf-8", "replace").split("\0") if p]

    def is_ignored(self, rel: str, is_dir: bool) -> bool:
        if self.is_git:
            if rel in self.tracked:
                return False
            key = rel + "/" if is_dir else rel
            if key in self.ignored:
                return True
            # 位于某个已忽略目录之下
            parts = rel.split("/")
            return any("/".join(parts[:i]) + "/" in self.ignored for i in range(1, len(parts)))
        name = rel.rsplit("/", 1)[-1]
        for pat in self.gitignore_patterns:
            anchored = pat.startswith("/")
            p = pat.strip("/")
            if pat.endswith("/") and not is_dir:
                continue
            if anchored or "/" in p:
                if fnmatch.fnmatch(rel, p) or rel.startswith(p + "/"):
                    return True
            elif fnmatch.fnmatch(name, p) or any(fnmatch.fnmatch(seg, p) for seg in rel.split("/")[:-1]):
                return True
        return False


def matches_any(name: str, globs: list[str]) -> bool:
    return any(fnmatch.fnmatch(name, g) for g in globs)


def naming_style(stem: str) -> str | None:
    if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)+", stem):
        return "kebab"
    if re.fullmatch(r"[a-z0-9]+(?:_[a-z0-9]+)+", stem):
        return "snake"
    return None


def audit(root: Path, max_root_files: int = 15, large_mb: float = 5.0) -> tuple[list[Finding], dict]:
    proj = Project(root)
    findings: list[Finding] = []
    add = findings.append

    def tracked_note(rel: str) -> str:
        return "（已被 git 跟踪）" if rel in proj.tracked else ""

    # ---------- 仓库级检查 ----------
    if not proj.is_git:
        add(Finding("not-git-repo", "warn", ".", "项目不是 git 仓库，删除和移动无法回滚",
                    "整理前先 git init 并做一次初始提交"))
    if not any((root / n).is_file() for n in ("README.md", "README", "README.rst", "readme.md")):
        add(Finding("missing-readme", "error", ".", "缺少 README", "参考 assets/README.template.md 补充"))
    if not (root / ".gitignore").is_file():
        add(Finding("missing-gitignore", "error", ".", "缺少 .gitignore", "参考 assets/gitignore/ 补充"))
    present_locks = [f for f in LOCKFILES if (root / f).is_file()]
    if len(present_locks) > 1:
        add(Finding("multiple-lockfiles", "warn", ".", f"存在多个包管理器的 lockfile：{', '.join(present_locks)}",
                    "只保留实际使用的包管理器对应的 lockfile"))

    # ---------- 遍历 ----------
    stats = {"files": 0, "dirs": 0, "skipped_dirs": 0}
    hashes: dict[tuple[int, str], list[str]] = {}
    by_dir_style: dict[tuple[str, str], dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))

    for dirpath, dirnames, filenames in os.walk(root):
        dpath = Path(dirpath)
        rel_dir = dpath.relative_to(root).as_posix()
        rel_dir = "" if rel_dir == "." else rel_dir
        depth = 0 if not rel_dir else rel_dir.count("/") + 1

        keep_dirs = []
        for d in sorted(dirnames):
            rel = f"{rel_dir}/{d}" if rel_dir else d
            if d in SKIP_DIRS:
                continue
            ignored = proj.is_ignored(rel, True)
            has_tracked = rel in proj.tracked_dirs
            if d in DEPENDENCY_DIRS or d.endswith(".egg-info"):
                if has_tracked:
                    add(Finding("tracked-artifact", "error", rel + "/", "依赖 / 缓存目录中的文件被 git 跟踪",
                                f"git rm -r --cached {rel} 并加入 .gitignore"))
                elif not ignored:
                    add(Finding("artifact-not-ignored", "error", rel + "/", "依赖 / 缓存目录未被 .gitignore 忽略",
                                "加入 .gitignore"))
                stats["skipped_dirs"] += 1
                continue
            if d in OUTPUT_DIRS:
                if has_tracked:
                    add(Finding("tracked-artifact", "warn", rel + "/", "疑似生成物目录中的文件被 git 跟踪",
                                "如确为生成物：git rm -r --cached 并加入 .gitignore，在 README 写明生成命令"))
                elif not ignored:
                    add(Finding("artifact-not-ignored", "warn", rel + "/", "疑似生成物目录未被忽略",
                                "如确为生成物，加入 .gitignore"))
                    stats["skipped_dirs"] += 1
                    continue
            if ignored:
                stats["skipped_dirs"] += 1
                continue
            keep_dirs.append(d)

            if not PORTABLE_NAME_RE.match(d):
                add(Finding("non-portable-name", "warn", rel + "/", "目录名含中文、空格或特殊字符",
                            "改为 ASCII kebab-case 名称"))
            if VERSION_SUFFIX_RE.search(d):
                add(Finding("version-suffix", "warn", rel + "/", "目录名带版本 / 副本后缀",
                            "确认当前版本后合并，旧版交给 git 历史"))
        dirnames[:] = keep_dirs

        if rel_dir:
            stats["dirs"] += 1
            visible = [f for f in filenames if not proj.is_ignored(f"{rel_dir}/{f}", False)]
            if not dirnames and not visible:
                add(Finding("empty-dir", "info", rel_dir + "/", "空目录（或只含被忽略的文件）",
                            "不需要就删除"))
            elif not dirnames and set(visible) <= {".gitkeep", ".keep"}:
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

            # 密钥文件：未忽略或被跟踪都是错误
            if matches_any(f, SECRET_FILE_GLOBS) and f not in SECRET_ALLOW:
                if is_tracked:
                    add(Finding("secret-tracked", "error", rel, "密钥 / 凭据文件被 git 跟踪",
                                "立即轮换密钥；git rm --cached 并加入 .gitignore；必要时清理历史"))
                elif not ignored:
                    add(Finding("secret-not-ignored", "error", rel, "密钥 / 凭据文件未被忽略",
                                "加入 .gitignore，提供 .env.example 代替"))
                continue
            if ignored:
                continue

            stats["files"] += 1
            stem, ext = os.path.splitext(f)
            try:
                size = fpath.stat().st_size
            except OSError:
                continue

            if matches_any(f, JUNK_FILE_GLOBS):
                add(Finding("junk-file", "warn", rel, f"系统 / 临时 / 日志文件{tracked_note(rel)}",
                            "删除并加入 .gitignore"))
                continue

            if not PORTABLE_NAME_RE.match(f):
                add(Finding("non-portable-name", "warn", rel, "文件名含中文、空格或特殊字符",
                            "改为 ASCII kebab-case 名称，中文写进文件标题"))

            if VERSION_SUFFIX_RE.search(stem):
                add(Finding("version-suffix", "warn", rel, "文件名带版本 / 副本后缀（v2、new、old、backup、copy、final…）",
                            "确认当前版本后合并，删除副本，历史交给 git"))

            if ext.lower() in (".md", ".txt") and stem.lower() not in STANDARD_DOCS and REPORT_DOC_RE.search(stem):
                add(Finding("ai-report-doc", "warn", rel, "疑似 AI 任务报告 / 总结类文档",
                            "有长期价值的内容合并进 README 或 docs/，其余删除；总结应写在 commit message"))

            if SCRATCH_NAME_RE.match(f) and not rel.startswith(("tests/", "test/")):
                add(Finding("scratch-file", "warn", rel, "疑似临时 / 调试脚本",
                            "删除；如需保留，按用途重命名并移入 scripts/"))

            if size == 0 and f not in EMPTY_OK:
                add(Finding("empty-file", "info", rel, "空文件", "不需要就删除"))

            if size > large_mb * 1024 * 1024:
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

    # ---------- 根目录 ----------
    root_files = sorted(
        p.name for p in root.iterdir()
        if p.is_file() and not proj.is_ignored(p.name, False)
    )
    if len(root_files) > max_root_files:
        add(Finding("root-clutter", "warn", ".", f"根目录有 {len(root_files)} 个文件（建议 ≤ {max_root_files}）",
                    "非入口级文件移入 src/、scripts/、docs/ 等目录"))
    # 这些规则已经给出了处理建议，不再重复报告位置问题
    already_flagged = {f.path for f in findings
                       if f.rule in ("junk-file", "ai-report-doc", "scratch-file", "secret-tracked")}
    for name in root_files:
        if matches_any(name, ROOT_ALLOWED_GLOBS) or name in already_flagged:
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext in (".md", ".txt", ".rst", ".docx", ".pdf"):
            hint = "文档移入 docs/"
        elif ext in (".py", ".js", ".ts", ".mjs", ".cjs", ".sh", ".ps1", ".bat"):
            hint = "脚本移入 scripts/（或删除一次性脚本）"
        elif ext in (".mp3", ".wav", ".mp4", ".mov", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"):
            hint = "素材移入 public/ 或 assets/；生成物则忽略"
        else:
            hint = "确认是否需要放在根目录"
        add(Finding("root-stray-file", "warn", name, "根目录下的非入口级文件", hint))

    # ---------- 重复文件 ----------
    for (_, _), paths in hashes.items():
        if len(paths) > 1:
            add(Finding("duplicate-file", "info", paths[0], f"内容完全相同的文件：{', '.join(paths)}",
                        "保留一份并修正引用"))

    # ---------- 命名风格混用 ----------
    for (d, ext), styles in by_dir_style.items():
        if len(styles) > 1 and all(len(v) >= 1 for v in styles.values()) and sum(map(len, styles.values())) >= 3:
            detail = "；".join(f"{k}: {', '.join(v[:3])}" for k, v in styles.items())
            add(Finding("mixed-naming", "info", (d or ".") + "/", f"同目录 {ext} 文件混用 kebab-case 与 snake_case（{detail}）",
                        "统一为该语言惯用风格"))

    # ---------- README 是否说明顶层目录 ----------
    readme = next((root / n for n in ("README.md", "readme.md", "README") if (root / n).is_file()), None)
    if readme:
        text = readme.read_text(encoding="utf-8", errors="replace")
        for p in sorted(root.iterdir()):
            if (p.is_dir() and not p.name.startswith(".") and p.name not in DEPENDENCY_DIRS
                    and not proj.is_ignored(p.name, True) and p.name not in text):
                add(Finding("readme-missing-dir", "info", p.name + "/", "README 未说明这个顶层目录的用途",
                            "在 README「目录结构」中补一句说明"))

    findings.sort(key=lambda x: (SEVERITY_ORDER[x.severity], x.rule, x.path))
    summary = {
        "root": str(root),
        "git": proj.is_git,
        "scanned_files": stats["files"],
        "scanned_dirs": stats["dirs"],
        "skipped_dirs": stats["skipped_dirs"],
        "counts": {s: sum(1 for f in findings if f.severity == s) for s in SEVERITY_ORDER},
    }
    return findings, summary


def render_text(findings: list[Finding], summary: dict) -> str:
    icons = {"error": "✖ ERROR", "warn": "▲ WARN ", "info": "● INFO "}
    lines = [
        f"项目整洁度审计：{summary['root']}",
        f"git 仓库：{'是' if summary['git'] else '否'}  扫描文件 {summary['scanned_files']} 个，"
        f"目录 {summary['scanned_dirs']} 个（跳过已忽略 / 依赖目录 {summary['skipped_dirs']} 个）",
        "",
    ]
    if not findings:
        lines.append("没有发现问题。")
        return "\n".join(lines)
    current = None
    for f in findings:
        if f.rule != current:
            current = f.rule
            lines.append(f"[{f.rule}]")
        lines.append(f"  {icons[f.severity]}  {f.path}  —  {f.message}")
        if f.suggestion:
            lines.append(f"           → {f.suggestion}")
    c = summary["counts"]
    lines += ["", f"合计：{c['error']} error，{c['warn']} warn，{c['info']} info",
              "提示：脚本是启发式检查，删除或移动前请先确认文件没有被引用。"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="项目整洁度审计（只读）")
    ap.add_argument("path", nargs="?", default=".", help="项目根目录，默认当前目录")
    ap.add_argument("--format", choices=["text", "json"], default="text")
    ap.add_argument("--fail-on", choices=["error", "warn", "never"], default="never",
                    help="达到该级别时以非零状态退出（用于 CI）")
    ap.add_argument("--max-root-files", type=int, default=15)
    ap.add_argument("--large-mb", type=float, default=5.0)
    args = ap.parse_args(argv)

    root = Path(args.path)
    if not root.is_dir():
        print(f"不是目录：{root}", file=sys.stderr)
        return 2
    findings, summary = audit(root, args.max_root_files, args.large_mb)

    if args.format == "json":
        print(json.dumps({"summary": summary, "findings": [asdict(f) for f in findings]},
                         ensure_ascii=False, indent=2))
    else:
        print(render_text(findings, summary))

    if args.fail_on == "never":
        return 0
    threshold = SEVERITY_ORDER[args.fail_on]
    return 1 if any(SEVERITY_ORDER[f.severity] <= threshold for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
