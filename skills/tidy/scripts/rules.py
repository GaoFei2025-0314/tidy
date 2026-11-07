"""tidy 的共享规则：命名 / 位置检查、项目配置、忽略判断、文件遍历。

audit.py（整体审计）、hook.py（各 Agent 的 hooks 与 git pre-commit）、refs.py（引用查找）都基于本模块，
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
CONFIG_PATH = ".tidy.json"
# 旧版位置，仍可读取；新生成的配置一律写到 CONFIG_PATH
LEGACY_CONFIG_PATHS = (".claude/tidy.json",)

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
# 密钥类规则：allow 豁免对它们无效，只能用 disable 显式关闭
SECRET_RULES = {"secret-file", "secret-tracked", "secret-not-ignored"}
# 包清单：生成物目录（dist/、build/…）只在项目根或清单文件旁边才算生成物
MANIFEST_FILES = ["package.json", "pyproject.toml", "setup.py", "Cargo.toml", "go.mod", "pom.xml",
                  "build.gradle", "build.gradle.kts", "deno.json"]

# 版本 / 副本后缀：foo_v2, foo-new, foo.backup, foo copy, foo_copy2, foo (1), 副本, 最终版
# 注意 "copy" 在内容项目里常指文案（hero-copy.md），所以只认系统复制产生的 " copy"、" copy 2" 和带编号的 _copy2
VERSION_SUFFIX_RE = re.compile(
    r"(?:[_\-. ](?:v\d+|new|old|backup|bak|final|tmp|temp|orig|draft\d*|fixed|updated)"
    r"|\scopy(?:\s?\d+)?|[_\-.]copy\d+|\s\(\d+\)|副本|最终版?|新版|旧版|备份)$",
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
# 临时 / 调试脚本名。SCRATCH_NAME_RE 是无意义的名字，任何位置都报；
# SCRATCH_PREFIX_RE 带描述（check_audio.py、debug_render.js），在已声明的工具目录里可能是正式工具，只在根目录报
SCRATCH_NAME_RE = re.compile(
    r"^(test\d*|tmp\d*|temp\d*|scratch\d*|debug\d*|untitled\d*|foo|bar|demo\d*|"
    r"playground|try\d*|a+|xxx)\.(py|js|ts|mjs|cjs|sh|txt|md|json)$",
    re.IGNORECASE,
)
SCRATCH_PREFIX_RE = re.compile(
    r"^(scratch|debug|untitled|try|check)[_\-]?\w+\.(py|js|ts|mjs|cjs|sh|txt|md|json)$",
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
    "components.json", "index.html", ".mcp.json", ".tidy.json",
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
    ".claude": "Claude Code 配置", ".codex": "Codex 配置", ".gemini": "Gemini CLI 配置",
    ".cursor": "Cursor 配置", ".agents": "通用 Agent 配置与 skills",
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
    """项目级配置，来自 .tidy.json（可选；旧版 .claude/tidy.json 也可读取）。"""
    layout: dict[str, str] = field(default_factory=dict)   # "src/": "源码"
    # 豁免：{"*": [对所有规则], "规则 id": [只对该规则]}；也接受旧格式的 glob 列表（等同 "*"）
    allow: dict[str, list[str]] | list[str] = field(default_factory=dict)
    keep_local: dict[str, str] = field(default_factory=dict)  # 本地保留、不进 git 的 glob → 原因
    reviewed: list[dict] = field(default_factory=list)        # 已人工核实的告警：{rule, path, reason, sig}
    root_allow: list[str] = field(default_factory=list)     # 额外允许放在根目录的文件 glob
    disable: list[str] = field(default_factory=list)        # 关闭的规则 id
    large_file_mb: float = 5.0
    max_root_files: int = 15
    hooks: bool = True                                       # false 时 hooks 不生效
    exists: bool = False
    error: str = ""                                          # 配置文件存在但无法解析时的原因

    def __post_init__(self):
        if isinstance(self.allow, list):
            self.allow = {"*": list(self.allow)} if self.allow else {}

    @property
    def layout_dirs(self) -> set[str]:
        return {k.strip("/") for k in self.layout}


def config_file(root: Path) -> Path:
    """当前生效的配置文件：优先 .tidy.json，其次旧版位置；都不存在时返回 .tidy.json。"""
    for rel in (CONFIG_PATH, *LEGACY_CONFIG_PATHS):
        if (root / rel).is_file():
            return root / rel
    return root / CONFIG_PATH


def load_config(root: Path) -> Config:
    p = config_file(root)
    if not p.is_file():
        return Config()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("顶层必须是对象")
        allow = data.get("allow", [])
        if isinstance(allow, list):
            allow = {"*": [str(g) for g in allow]} if allow else {}
        elif isinstance(allow, dict):
            allow = {str(k): _str_list(v, f"allow.{k}") for k, v in allow.items()}
        else:
            raise ValueError("allow 必须是 glob 列表或 {规则 id: glob 列表}")
        keep = data.get("keepLocal", {})
        if isinstance(keep, list):
            keep = {str(g): "" for g in keep}
        elif not isinstance(keep, dict):
            raise ValueError("keepLocal 必须是 glob 列表或 {glob: 原因}")
        reviewed = data.get("reviewed", [])
        if not isinstance(reviewed, list) or not all(
                isinstance(r, dict) and isinstance(r.get("rule"), str) and isinstance(r.get("path"), str)
                for r in reviewed):
            raise ValueError("reviewed 必须是 [{rule, path, reason, sig}] 列表")
        layout = data.get("layout", {})
        if not isinstance(layout, dict):
            raise ValueError("layout 必须是 {目录: 说明}")
        return Config(
            layout={str(k): str(v) for k, v in layout.items()},
            allow=allow,
            keep_local={str(k): str(v) for k, v in keep.items()},
            reviewed=reviewed,
            root_allow=_str_list(data.get("rootAllow", []), "rootAllow"),
            disable=_str_list(data.get("disable", []), "disable"),
            large_file_mb=float(data.get("largeFileMB", 5.0)),
            max_root_files=int(data.get("maxRootFiles", 15)),
            hooks=bool(data.get("hooks", True)),
            exists=True,
        )
    except (OSError, ValueError, TypeError) as e:  # JSONDecodeError 是 ValueError 的子类
        return Config(exists=True, error=f"{p.relative_to(root).as_posix()} 无法解析，已按默认规则检查：{e}")


def _str_list(v, name: str) -> list[str]:
    if not isinstance(v, list):
        raise ValueError(f"{name} 必须是列表")
    return [str(x) for x in v]


def matches_any(name: str, globs: list[str]) -> bool:
    return any(fnmatch.fnmatch(name, g) for g in globs)


def path_matches(rel: str, pattern: str) -> bool:
    """rel 本身或它的某个上级目录匹配 glob。支持 ** 匹配零或多层目录。"""
    p = pattern.strip().rstrip("/")
    if not p:
        return False
    variants = {p, p.replace("/**/", "/")}
    if p.startswith("**/"):
        variants.add(p[3:])
    parts = rel.strip("/").split("/")
    prefixes = ["/".join(parts[:i]) for i in range(1, len(parts) + 1)]
    return any(fnmatch.fnmatch(pre, v) for v in variants for pre in prefixes)


def is_exempt(rel: str, cfg: Config, rule: str | None = None) -> bool:
    """rel 是否被 allow 豁免。密钥类规则永远不被 allow 豁免。"""
    if rule in SECRET_RULES:
        return False
    globs = list(cfg.allow.get("*", []))
    if rule:
        globs += cfg.allow.get(rule, [])
    return any(path_matches(rel, g) for g in globs)


def keep_local_match(rel: str, cfg: Config) -> str | None:
    """rel 匹配 keepLocal 时返回对应 glob。"""
    return next((g for g in cfg.keep_local if path_matches(rel, g)), None)


def apply_config(findings: list[Finding], cfg: Config) -> list[Finding]:
    return [f for f in findings if f.rule not in cfg.disable and not is_exempt(f.path, cfg, f.rule)]


def is_output_dir(root: Path | None, rel: str) -> bool:
    """rel 是否是生成物目录：名字在 OUTPUT_DIRS 里，且位于项目根或包清单文件旁边。

    docs/验证记录/L12/coverage/ 这种嵌在内容目录里的同名目录不算。
    """
    parts = rel.strip("/").split("/")
    if parts[-1] not in OUTPUT_DIRS:
        return False
    if len(parts) == 1:
        return True
    if root is None:
        return False
    parent = root.joinpath(*parts[:-1])
    return any((parent / m).is_file() for m in MANIFEST_FILES)


def is_dependency_dir(name: str) -> bool:
    return name in DEPENDENCY_DIRS or name.endswith(".egg-info")


def artifact_dir_of(rel: str, root: Path | None = None) -> str | None:
    """路径位于依赖 / 生成物目录下时，返回该目录的相对路径（带 /）。"""
    parts = rel.strip("/").split("/")
    for i, seg in enumerate(parts[:-1] if not rel.endswith("/") else parts):
        if is_dependency_dir(seg) or is_output_dir(root, "/".join(parts[: i + 1])):
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
    if not is_dir and not (set(parts[:-1]) & TEST_DIRS) and (
            SCRATCH_NAME_RE.match(name) or (len(parts) == 1 and SCRATCH_PREFIX_RE.match(name))):
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
                    if line and not line.startswith("#"):
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

    EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

    def head(self) -> str:
        """当前 HEAD 的 commit；空仓库返回空树，便于和 git diff 配合。"""
        return self._git(["rev-parse", "--verify", "-q", "HEAD"]) or self.EMPTY_TREE

    def added_since(self, base: str) -> list[str]:
        """相对 base 新增、且已进入暂存区或已提交的文件（git add / git commit 之后不再是"未跟踪"）。"""
        return self._git_z(["diff", "--cached", "--name-only", "-z", "--no-renames", "--diff-filter=A", base])

    def changed_since(self, base: str) -> list[str]:
        """相对 base 新增或修改的文件（含暂存区和工作区），加上未跟踪文件。"""
        changed = self._git_z(["diff", "--name-only", "-z", "--no-renames", "--diff-filter=AM", base])
        return sorted(set(changed) | set(self.untracked()))

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
        """近似 git 的匹配：按顺序检查，最后一条命中的规则生效，! 表示重新包含。"""
        name = rel.rsplit("/", 1)[-1]
        segs = rel.split("/")
        ignored = False
        for raw in self.gitignore_patterns:
            negate = raw.startswith("!")
            pat = raw[1:] if negate else raw
            anchored = pat.startswith("/")
            p = pat.strip("/")
            dir_only = pat.endswith("/")
            variants = {p, p.replace("/**/", "/")}
            if p.startswith("**/"):
                variants.add(p[3:])
            hit = False
            if anchored or "/" in p:
                for v in variants:
                    if rel.startswith(v + "/") or ((is_dir or not dir_only) and fnmatch.fnmatch(rel, v)) \
                            or any(fnmatch.fnmatch("/".join(segs[:i]), v) for i in range(1, len(segs))):
                        hit = True
                        break
            else:
                hit = any(fnmatch.fnmatch(s, p) for s in segs[:-1]) or \
                    ((is_dir or not dir_only) and fnmatch.fnmatch(name, p))
            if hit:
                ignored = not negate
        return ignored


def iter_files(root: Path, proj: Project) -> Iterator[str]:
    """遍历未被忽略的文件（相对路径），跳过依赖 / 生成物 / VCS 目录。"""
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        rel_dir = "" if rel_dir == "." else rel_dir
        keep = []
        for d in dirnames:
            rel = f"{rel_dir}/{d}" if rel_dir else d
            if d in SKIP_DIRS or is_dependency_dir(d) or is_output_dir(root, rel):
                continue
            if proj.is_ignored(rel, True):
                continue
            keep.append(d)
        dirnames[:] = keep
        for f in filenames:
            rel = f"{rel_dir}/{f}" if rel_dir else f
            if not proj.is_ignored(rel, False):
                yield rel
