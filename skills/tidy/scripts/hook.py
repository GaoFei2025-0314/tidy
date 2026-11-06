#!/usr/bin/env python3
"""Claude Code hooks：把整洁规范从"建议"变成"机制"。

    hook.py session-start   会话开始：注入核心规则和本项目目录约定；记录文件基线
    hook.py pre-write       Write 新文件前：名字 / 位置不合规就拦截，并告诉 Claude 该怎么做
    hook.py stop            每轮结束：检查本轮新增的文件（包括 Bash 创建的），不合规就要求先清理

只检查"新增"的文件，老项目里已有的问题不会反复打扰；整理老项目请用 audit.py。
在 .claude/tidy.json 里写 "hooks": false 可对单个项目关闭。

hook 输入是 stdin 上的 JSON。退出码 2 表示拦截，stderr 内容会反馈给 Claude。
任何意外错误都放行（退出码 0），绝不因为 hook 自身的问题卡住用户。
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rules import (  # noqa: E402
    CONFIG_PATH, Config, Finding, Project, apply_config, artifact_dir_of, check_path, iter_files, keep_local_match,
    load_config,
)

CORE_RULES = """\
[tidy] 本项目启用了文件整洁规范：
- 新建文件前先问：能否并入已有文件？该放哪个目录？名字是否说明用途（ASCII、与同目录风格一致）？是否应被 .gitignore？
- 不要创建：临时 / 调试脚本、*_v2 / *_new / *_old / *.bak 副本、*_SUMMARY.md / *_REPORT.md 等任务报告、根目录杂项文件。
- 临时文件放 .scratch/（需被忽略）或系统临时目录，任务结束前删除；总结写在回复和 commit message 里。
- 生成物（build/、out/、渲染结果、日志）和依赖不提交；删除或批量移动文件前先征得用户同意。"""


def project_root(data: dict) -> Path:
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()).resolve()


def state_file(root: Path, session_id: str) -> Path:
    key = hashlib.sha1(str(root).encode()).hexdigest()[:12]
    d = Path(tempfile.gettempdir()) / "tidy" / key
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{session_id or 'default'}.json"


def snapshot(root: Path, proj: Project, base: str = "") -> set[str]:
    """当前"未跟踪且未忽略"的文件，加上相对会话开始时的 commit（base）新增并已 git add / commit 的文件。

    非 git 项目则为全部未忽略文件。依赖 / 生成物目录折叠成一个条目，避免 node_modules 之类刷屏。
    """
    if proj.is_git:
        files = proj.untracked() + (proj.added_since(base) if base else [])
    else:
        files = list(iter_files(root, proj))
    result = set()
    for rel in files:
        result.add(artifact_dir_of(rel, root) or rel)
    if not proj.is_git:
        # iter_files 不进入依赖 / 生成物目录，单独记录它们是否存在
        for p in root.iterdir():
            if p.is_dir() and artifact_dir_of(p.name + "/") and not proj.is_ignored(p.name, True):
                result.add(p.name + "/")
    return result


def save(path: Path, files: set[str], base: str) -> None:
    path.write_text(json.dumps({"base": base, "files": sorted(files)}, ensure_ascii=False), encoding="utf-8")


def load(path: Path) -> tuple[set[str], str] | None:
    """返回（基线文件集合, 会话开始时的 commit）。兼容旧版只存列表的状态文件。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(data, list):
        return set(data), ""
    return set(data.get("files", [])), data.get("base", "")


def format_findings(findings: list[Finding]) -> str:
    lines = []
    for f in findings:
        lines.append(f"- {f.path}：{f.message}")
        if f.suggestion:
            lines.append(f"  → {f.suggestion}")
    return "\n".join(lines)


def check_new_entries(new: set[str], cfg: Config) -> list[Finding]:
    findings: list[Finding] = []
    for rel in sorted(new):
        glob = keep_local_match(rel, cfg)
        if glob:  # 快照里只有未忽略的文件，所以匹配 keepLocal 就说明漏了忽略规则
            findings.append(Finding("keep-local-not-ignored", "warn", rel,
                                    f"按 keepLocal（{glob}）应本地保留、不进 git，但未被忽略",
                                    "把该 glob 加进 .gitignore（可用 audit.py --fix-gitignore）；不要删除文件"))
            continue
        if rel.endswith("/"):
            findings.append(Finding("artifact-not-ignored", "warn", rel, "新出现的依赖 / 生成物目录未被忽略",
                                    "加入 .gitignore；如果它确实是源码目录，在 .claude/tidy.json 的 allow 中豁免"))
            continue
        for f in check_path(rel, cfg):
            if f.rule == "secret-file":
                f.message = "密钥 / 凭据文件未被忽略"
            findings.append(f)
    findings = apply_config(findings, cfg)
    seen, unique = set(), []
    for f in findings:
        if (f.rule, f.path) not in seen:
            seen.add((f.rule, f.path))
            unique.append(f)
    return unique


def on_session_start(data: dict, root: Path, cfg: Config) -> int:
    proj = Project(root)
    base = proj.head() if proj.is_git else ""
    save(state_file(root, data.get("session_id", "")), snapshot(root, proj, base), base)
    out = [CORE_RULES]
    if cfg.error:
        out.append(f"注意：{cfg.error}。请修正该文件。")
    if cfg.layout:
        out.append(f"本项目目录约定（{CONFIG_PATH}）——新文件必须放进这些目录，确需新目录先登记：")
        out += [f"  {k.rstrip('/')}/ — {v}" for k, v in cfg.layout.items()]
    else:
        out.append(f"本项目尚未声明目录约定（{CONFIG_PATH}）。用户要求整理项目时，使用 tidy skill。")
    if cfg.keep_local:
        out.append("本地保留、不进 git 的文件（不要当作生成物删除）：")
        out += [f"  {g}" + (f" — {why}" if why else "") for g, why in cfg.keep_local.items()]
    print("\n".join(out))
    return 0


def on_pre_write(data: dict, root: Path, cfg: Config) -> int:
    file_path = (data.get("tool_input") or {}).get("file_path")
    if not file_path:
        return 0
    path = Path(file_path)
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    if path.exists():  # 只管新建，修改已有文件不拦截
        return 0
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:  # 项目外（如系统临时目录）不管
        return 0
    if artifact_dir_of(rel, root):
        return 0
    proj = Project(root)
    if proj.check_ignore(rel):  # 写进已忽略的位置（临时区、生成物目录）不管
        return 0
    findings = [f for f in check_path(rel, cfg) if f.rule != "secret-file"]
    if not findings:
        return 0
    print(
        f"[tidy] 拦截新建文件 {rel}：\n{format_findings(findings)}\n"
        f"请换一种做法（合并进已有文件 / 换位置 / 换名字 / 不落盘）。"
        f"如果这是用户明确要求的，把该路径加入 {CONFIG_PATH} 的 allow 后重试。",
        file=sys.stderr,
    )
    return 2


def on_stop(data: dict, root: Path, cfg: Config) -> int:
    proj = Project(root)
    sf = state_file(root, data.get("session_id", ""))
    state = load(sf)
    if state is None or (proj.is_git and not state[1]):
        # 没有基线（会话中途装的插件，或旧版状态文件）：以当前状态为基线
        base = proj.head() if proj.is_git else ""
        save(sf, snapshot(root, proj, base), base)
        return 0
    baseline, base = state
    current = snapshot(root, proj, base)
    if data.get("stop_hook_active"):
        # 已经提醒过一次：接受当前状态，避免死循环
        save(sf, current, base)
        return 0
    findings = check_new_entries(current - baseline, cfg)
    if not findings:
        save(sf, current, base)
        return 0
    print(
        "[tidy] 结束前检查：本轮新增的文件有不符合整洁规范的地方，请先处理：\n"
        f"{format_findings(findings)}\n"
        "处理方式：删除临时文件；把副本合并回原文件；移动到正确目录；或补进 .gitignore。"
        f"如果是用户明确要求保留的，加入 {CONFIG_PATH} 的 allow，并在回复中说明。",
        file=sys.stderr,
    )
    return 2


HANDLERS = {"session-start": on_session_start, "pre-write": on_pre_write, "stop": on_stop}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in HANDLERS:
        print(f"用法：hook.py {{{'|'.join(HANDLERS)}}}", file=sys.stderr)
        return 0
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
        root = project_root(data)
        cfg = load_config(root)
        if not cfg.hooks:
            return 0
        return HANDLERS[sys.argv[1]](data, root, cfg)
    except Exception as e:  # noqa: BLE001 — hook 自身出错时放行，不能卡住用户
        print(f"[tidy] hook 内部错误，已放行：{e}", file=sys.stderr)
        return 0


if __name__ == "__main__":
    sys.exit(main())
