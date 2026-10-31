"""project-hygiene 的共享规则：命名 / 位置检查、项目配置、忽略判断、文件遍历。

audit.py（整体审计）、hook.py（Claude Code hooks）、refs.py（引用查找）都基于本模块，
保证三者对"什么是不规范"的判断完全一致。只依赖 Python 标准库。
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

SEVERITY_ORDER = {"error": 0, "warn": 1, "info": 2}
CONFIG_PATH = ".claude/hygiene.json"

# 依赖 / 缓存目录：出现即应被忽略，扫描时不进入
DEPENDENCY_DIRS = {
    "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".ipynb_checkpoints", ".parcel-cache", ".turbo", ".next", ".nuxt",
    ".cache", ".tox", ".gradle", ".scratch",
}
# 常见生成物目录：通常应被忽略，但少数项目里是源码，因此只给 warn
OUTPUT_DIRS = {"build", "dist", "out", "coverage", "htmlcov", "target", "renders"}
# 永不扫描
SKIP_DIRS = {".git", ".hg", ".svn"}
# 测试目录：其中的 test_*.py 等不算临时脚本
TEST_DIRS = {"tests", "test", "__tests__", "spec", "e2e"}

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
    "components.json", "index.html", ".mcp.json",
]
LOCKFILES = ["package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb", "bun.lock"]
PORTABLE_NAME_RE = re.compile(r"^[A-Za-z0-9._\-@+]+$")

# init 时为常见目录预填的说明
KNOWN_DIR_PURPOSES = {
    "src": "源码", "lib": "库代码", "app": "应用代码（框架约定）", "pages": "页面（框架约定）",
    "components": "组件", "public": "原样提供的静态资源", "assets": "源素材",
    "scripts": "开发 / 构建脚本", "tools": "独立的辅助工具", "docs": "文档",
    "tests": "测试", "test": "测试", "examples": "示例", "config": "配置",
    "packages": "monorepo 共享包", "apps": "monorepo 应用", ".github": "GitHub 配置与 CI",
    ".claude": "Claude Code 配置",
}


@dataclass
class Finding:
    rule: str
    severity: str
    path: str
    message: str
    suggestion: str = ""


@dataclass
class Config:
    """项目级配置，来自 .claude/hygiene.json（可选）。"""
    layout: dict[str, str] = field(default_factory=dict)   # "src/": "源码"
    allow: list[str] = field(default_factory=list)          # 豁免的路径 glob
    root_allow: list[str] = field(default_factory=list)     # 额外允许放在根目录的文件 glob
    disable: list[str] = field(default_factory=list)        # 关闭的规则 id
    large_file_mb: float = 5.0
    max_root_files: int = 15
    hooks: bool = True                                       # false 时 hooks 不生效
    exists: bool = False

    @property
    def layout_dirs(self) -> set[str]:
        return {k.strip("/") for k in self.layout}


def load_config(root: Path) -> Config:
    p = root / CONFIG_PATH
    if not p.is_file():
        return Config()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Config()
    return Config(
        layout=dict(data.get("layout", {})),
        allow=list(data.get("allow", [])),
        root_allow=list(data.get("rootAllow", [])),
        disable=list(data.get("disable", [])),
        large_file_mb=float(data.get("largeFileMB", 5.0)),
        max_root_files=int(data.get("maxRootFiles", 15)),
        hooks=bool(data.get("hooks", True)),
        exists=True,
    )


def matches_any(name: str, globs: list[str]) -> bool:
    return any(fnmatch.fnmatch(name, g) for g in globs)


def is_exempt(rel: str, cfg: Config) -> bool:
    rel = rel.rstrip("/")
    return any(fnmatch.fnmatch(rel, g.rstrip("/")) or rel.startswith(g.rstrip("/") + "/") for g in cfg.allow)


def apply_config(findings: list[Finding], cfg: Config) -> list[Finding]:
    return [f for f in findings if f.rule not in cfg.disable and not is_exempt(f.path, cfg)]


def artifact_dir_of(rel: str) -> str | None:
    """路径位于依赖 / 生成物目录下时，返回该目录的相对路径（带 /）。"""
    parts = rel.strip("/").split("/")
    for i, seg in enumerate(parts[:-1] if not rel.endswith("/") else parts):
        if seg in DEPENDENCY_DIRS or seg in OUTPUT_DIRS or seg.endswith(".egg-info"):
            return "/".join(parts[: i + 1]) + "/"
    return None


def layout_hint(cfg: Config) -> str:
    if not cfg.layout:
        return ""
    return "；本项目目录约定：" + "，".join(f"{k.rstrip('/')}/ = {v}" for k, v in cfg.layout.items())


def check_path(rel: str, cfg: Config, is_dir: bool = False) -> list[Finding]:
    """只根据路径本身（名字和位置）判断问题，不读文件内容、不看 git 状态。

    hook 用它拦截新文件，audit 用它检查每个已有文件。返回的问题都是 warn 及以上。
    密钥文件返回 rule="secret-file"，是否被忽略 / 跟踪由调用方判断。
    """
    rel = rel.strip("/")
    parts = rel.split("/")
    name = parts[-1]
    stem, ext = (name, "") if is_dir else os.path.splitext(name)
    top = parts[0]
    shown = rel + ("/" if is_dir else "")
    out: list[Finding] = []

    if not is_dir and matches_any(name, SECRET_FILE_GLOBS) and name not in SECRET_ALLOW:
        out.append(Finding("secret-file", "error", shown, "密钥 / 凭据文件",
                           "必须被 .gitignore 忽略；提供 .env.example 代替"))
        return apply_config(out, cfg)
    if not is_dir and matches_any(name, JUNK_FILE_GLOBS):
        out.append(Finding("junk-file", "warn", shown, "系统 / 临时 / 日志文件", "删除并加入 .gitignore"))
        return apply_config(out, cfg)

    if not PORTABLE_NAME_RE.match(name):
        out.append(Finding("non-portable-name", "warn", shown, "名称含中文、空格或特殊字符",
                           "改为 ASCII kebab-case 名称，中文写进文件标题"))
    if VERSION_SUFFIX_RE.search(stem):
        out.append(Finding("version-suffix", "warn", shown, "名称带版本 / 副本后缀（v2、new、old、backup、copy、final…）",
                           "直接修改原文件，历史交给 git；已有副本则确认当前版本后合并删除"))
    placement_reported = False
    if (not is_dir and ext.lower() in (".md", ".txt") and stem.lower() not in STANDARD_DOCS
            and top != "docs" and REPORT_DOC_RE.search(stem)):
        out.append(Finding("ai-report-doc", "warn", shown, "疑似 AI 任务报告 / 总结类文档",
                           "总结写进回复和 commit message；有长期价值的内容合并进 README 或 docs/ 已有文档"))
        placement_reported = True
    if not is_dir and SCRATCH_NAME_RE.match(name) and not (set(parts[:-1]) & TEST_DIRS):
        out.append(Finding("scratch-file", "warn", shown, "疑似临时 / 调试脚本",
                           "临时文件放 .scratch/（已忽略）或系统临时目录，用完即删；需要长期保留就按用途命名并放进 scripts/"))
        placement_reported = True

    if len(parts) == 1 and not is_dir and not placement_reported \
            and not matches_any(name, ROOT_ALLOWED_GLOBS + cfg.root_allow):
        e = ext.lower()
        if e in (".md", ".txt", ".rst", ".docx", ".pdf"):
            hint = "文档放 docs/"
        elif e in (".py", ".js", ".ts", ".mjs", ".cjs", ".sh", ".ps1", ".bat"):
            hint = "脚本放 scripts/（一次性脚本不要落盘）"
        elif e in (".mp3", ".wav", ".mp4", ".mov", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"):
            hint = "素材放 public/ 或 assets/；生成物则忽略"
        else:
            hint = "确认是否需要放在根目录"
        out.append(Finding("root-stray-file", "warn", shown, "根目录下的非入口级文件", hint + layout_hint(cfg)))

    if (cfg.layout and len(parts) >= (1 if is_dir else 2) and not top.startswith(".")
            and top not in cfg.layout_dirs and top not in DEPENDENCY_DIRS and top not in OUTPUT_DIRS):
        out.append(Finding("undeclared-dir", "warn", top + "/", f"顶层目录 {top}/ 不在 {CONFIG_PATH} 的 layout 中",
                           "放进已声明的目录；确需新目录时，先在 layout 和 README「目录结构」中登记" + layout_hint(cfg)))
    return apply_config(out, cfg)


class Project:
    """封装 git 状态与忽略规则判断。非 git 项目退化为解析根目录 .gitignore。"""

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
                segs = t.split("/")[:-1]
                for i in range(1, len(segs) + 1):
                    self.tracked_dirs.add("/".join(segs[:i]))
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
            out = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True, check=True)
            return out.stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            return ""

    def _git_z(self, args: list[str]) -> list[str]:
        try:
            out = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            return []
        return [p for p in out.stdout.decode("utf-8", "replace").split("\0") if p]

    def untracked(self) -> list[str]:
        """未跟踪且未被忽略的文件（仅 git 项目）。"""
        return self._git_z(["ls-files", "-z", "--others", "--exclude-standard"])

    def is_ignored(self, rel: str, is_dir: bool) -> bool:
        if self.is_git:
            if rel in self.tracked:
                return False
            if (rel + "/" if is_dir else rel) in self.ignored:
                return True
            segs = rel.split("/")
            return any("/".join(segs[:i]) + "/" in self.ignored for i in range(1, len(segs)))
        return self._match_gitignore(rel, is_dir)

    def check_ignore(self, rel: str) -> bool:
        """判断一个可能尚不存在的路径是否会被忽略。"""
        if self.is_git:
            r = subprocess.run(["git", "-C", str(self.root), "check-ignore", "-q", "--no-index", rel],
                               capture_output=True)
            return r.returncode == 0
        return self._match_gitignore(rel, False)

    def _match_gitignore(self, rel: str, is_dir: bool) -> bool:
        name = rel.rsplit("/", 1)[-1]
        segs = rel.split("/")
        for pat in self.gitignore_patterns:
            anchored = pat.startswith("/")
            p = pat.strip("/")
            dir_only = pat.endswith("/")
            if anchored or "/" in p:
                if rel.startswith(p + "/") or ((is_dir or not dir_only) and fnmatch.fnmatch(rel, p)):
                    return True
            else:
                if any(fnmatch.fnmatch(s, p) for s in segs[:-1]):
                    return True
                if (is_dir or not dir_only) and fnmatch.fnmatch(name, p):
                    return True
        return False


def iter_files(root: Path, proj: Project) -> Iterator[str]:
    """遍历未被忽略的文件（相对路径），跳过依赖 / 生成物 / VCS 目录。"""
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        rel_dir = "" if rel_dir == "." else rel_dir
        keep = []
        for d in dirnames:
            rel = f"{rel_dir}/{d}" if rel_dir else d
            if d in SKIP_DIRS or d in DEPENDENCY_DIRS or d in OUTPUT_DIRS or d.endswith(".egg-info"):
                continue
            if proj.is_ignored(rel, True):
                continue
            keep.append(d)
        dirnames[:] = keep
        for f in filenames:
            rel = f"{rel_dir}/{f}" if rel_dir else f
            if not proj.is_ignored(rel, False):
                yield rel
