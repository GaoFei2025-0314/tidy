#!/usr/bin/env python3
"""tidy 的自动检查：把整洁规范从"建议"变成"机制"。同一套检查，适配多个 Agent 和 git。

    hook.py session-start [--agent A]   会话开始：注入核心规则和本项目目录约定；记录文件基线
    hook.py pre-write     [--agent A]   新建文件前：名字 / 位置不合规就拦截，并告诉 Agent 该怎么做
    hook.py stop          [--agent A]   每轮结束：检查本轮新增的文件（包括命令行创建的），不合规就要求先清理
    hook.py pre-commit                  git pre-commit：检查本次提交新增的文件，任何 Agent 和人都适用

A = claude | codex | gemini | cursor。省略时按输入自动判断。各 Agent 的配置由 install.py 生成。

只检查"新增"的文件，老项目里已有的问题不会反复打扰；整理老项目请用 audit.py。
在 .tidy.json 里写 "hooks": false 可对单个项目关闭。

输入是 stdin 上的 JSON（pre-commit 除外），输出按各 Agent 的协议写 JSON 到 stdout，退出码始终为 0。
任何意外错误都放行，绝不因为 hook 自身的问题卡住用户。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rules import (  # noqa: E402
    CONFIG_PATH, Config, Finding, Project, apply_config, artifact_dir_of, check_path, iter_files, keep_local_match,
    load_config,
)

AGENTS = ("claude", "codex", "gemini", "cursor")

CORE_RULES = """\
[tidy] 本项目启用了文件整洁规范：
- 新建文件前先问：能否并入已有文件？该放哪个目录？名字是否说明用途（ASCII、与同目录风格一致）？是否应被 .gitignore？
- 不要创建：临时 / 调试脚本、*_v2 / *_new / *_old / *.bak 副本、*_SUMMARY.md / *_REPORT.md 等任务报告、根目录杂项文件。
- 临时文件放 .scratch/（需被忽略）或系统临时目录，任务结束前删除；总结写在回复和 commit message 里。
- 生成物（build/、out/、渲染结果、日志）和依赖不提交；删除或批量移动文件前先征得用户同意。"""

# Codex 的 apply_patch 把新文件写在补丁文本里：*** Add File: path / *** Move to: path
PATCH_NEW_FILE_RE = re.compile(r"^\*\*\* (?:Add File|Move to): (.+?)\s*$", re.MULTILINE)


# ---------------------------------------------------------------- 输入适配

def detect_agent(data: dict, explicit: str = "") -> str:
    if explicit in AGENTS:
        return explicit
    if "cursor_version" in data or "conversation_id" in data:
        return "cursor"
    if os.environ.get("GEMINI_SESSION_ID") or data.get("hook_event_name") in ("BeforeTool", "AfterAgent"):
        return "gemini"
    if "turn_id" in data:
        return "codex"
    return "claude"


def git_toplevel(path: Path) -> Path | None:
    try:
        out = subprocess.run(["git", "-C", str(path), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, check=True)
        return Path(out.stdout.strip()).resolve()
    except (subprocess.CalledProcessError, FileNotFoundError, NotADirectoryError):
        return None


def project_root(data: dict) -> Path:
    roots = data.get("workspace_roots") or []
    raw = (os.environ.get("CLAUDE_PROJECT_DIR") or os.environ.get("GEMINI_PROJECT_DIR")
           or (roots[0] if roots else "") or data.get("cwd") or os.getcwd())
    p = Path(raw).resolve()
    # Codex 等可能从子目录启动，统一用仓库根目录
    return git_toplevel(p) or p


def session_key(data: dict) -> str:
    return str(data.get("session_id") or data.get("conversation_id") or os.environ.get("GEMINI_SESSION_ID") or "")


def new_file_candidates(data: dict) -> list[str]:
    """从各 Agent 的写文件工具参数里取出目标路径。"""
    ti = data.get("tool_input")
    if isinstance(ti, str):
        try:
            ti = json.loads(ti)
        except ValueError:
            ti = {"command": ti}
    if not isinstance(ti, dict):
        return []
    paths = [ti[k] for k in ("file_path", "path", "target_file", "filePath") if isinstance(ti.get(k), str)]
    for k in ("command", "patch", "input"):
        v = ti.get(k)
        if isinstance(v, str) and "*** " in v:
            paths += PATCH_NEW_FILE_RE.findall(v)
    return list(dict.fromkeys(paths))


# ---------------------------------------------------------------- 输出适配

def emit(agent: str, event: str, *, block: str = "", context: str = "") -> int:
    """按各 Agent 的 hook 协议输出。block 非空表示拦截，context 是会话开始时注入的文本。"""
    out: dict | None = None
    if event == "session-start":
        if agent == "cursor":
            out = {"additional_context": context}
        else:  # claude / codex / gemini 都认 hookSpecificOutput.additionalContext
            out = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}
    elif event == "pre-write":
        if agent == "cursor":
            out = ({"permission": "deny", "agent_message": block, "user_message": "[tidy] 已拦截不合规的新文件"}
                   if block else {"permission": "allow"})
        elif agent == "gemini":
            out = {"decision": "deny", "reason": block} if block else {}
        elif block:  # claude / codex
            out = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                          "permissionDecisionReason": block}}
    elif event == "stop":
        if not block:
            out = {}
        elif agent == "cursor":
            out = {"followup_message": block}
        elif agent == "gemini":
            out = {"decision": "deny", "reason": block}
        else:  # claude / codex
            out = {"decision": "block", "reason": block}
    if out is not None:
        print(json.dumps(out, ensure_ascii=False))
    return 0


def allow_output(agent: str, event: str) -> int:
    """出错或关闭时的放行输出。Cursor 的拦截类 hook 收不到合法 JSON 会直接拦截，所以必须输出。"""
    if event == "pre-write" and agent == "cursor":
        print(json.dumps({"permission": "allow"}))
    elif event in ("stop", "pre-write") and agent in ("codex", "gemini", "cursor"):
        print("{}")
    return 0


# ---------------------------------------------------------------- 基线

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


# ---------------------------------------------------------------- 检查

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
                                    f"加入 .gitignore；如果它确实是源码目录，在 {CONFIG_PATH} 的 allow 中豁免"))
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


def on_session_start(data: dict, root: Path, cfg: Config, agent: str) -> int:
    proj = Project(root)
    base = proj.head() if proj.is_git else ""
    save(state_file(root, session_key(data)), snapshot(root, proj, base), base)
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
    return emit(agent, "session-start", context="\n".join(out))


def on_pre_write(data: dict, root: Path, cfg: Config, agent: str) -> int:
    proj = None
    blocked: list[tuple[str, list[Finding]]] = []
    for file_path in new_file_candidates(data):
        path = Path(file_path)
        if not path.is_absolute():
            path = Path(data.get("cwd") or root) / path
        path = path.resolve()
        if path.exists():  # 只管新建，修改已有文件不拦截
            continue
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:  # 项目外（如系统临时目录）不管
            continue
        if artifact_dir_of(rel, root):
            continue
        proj = proj or Project(root)
        if proj.check_ignore(rel):  # 写进已忽略的位置（临时区、生成物目录）不管
            continue
        findings = [f for f in check_path(rel, cfg) if f.rule != "secret-file"]
        if findings:
            blocked.append((rel, findings))
    if not blocked:
        return emit(agent, "pre-write")
    parts = [f"[tidy] 拦截新建文件 {rel}：\n{format_findings(fs)}" for rel, fs in blocked]
    msg = ("\n".join(parts) + "\n请换一种做法（合并进已有文件 / 换位置 / 换名字 / 不落盘）。"
           f"如果这是用户明确要求的，把该路径加入 {CONFIG_PATH} 的 allow 后重试。")
    return emit(agent, "pre-write", block=msg)


def on_stop(data: dict, root: Path, cfg: Config, agent: str) -> int:
    proj = Project(root)
    sf = state_file(root, session_key(data))
    state = load(sf)
    if state is None or (proj.is_git and not state[1]):
        # 没有基线（会话中途装的 hook，或旧版状态文件）：以当前状态为基线
        base = proj.head() if proj.is_git else ""
        save(sf, snapshot(root, proj, base), base)
        return emit(agent, "stop")
    baseline, base = state
    current = snapshot(root, proj, base)
    # 已经提醒过一次（Cursor 用 loop_count 表示）：接受当前状态，避免死循环
    if data.get("stop_hook_active") or (data.get("loop_count") or 0) > 0:
        save(sf, current, base)
        return emit(agent, "stop")
    findings = check_new_entries(current - baseline, cfg)
    if not findings:
        save(sf, current, base)
        return emit(agent, "stop")
    msg = ("[tidy] 结束前检查：本轮新增的文件有不符合整洁规范的地方，请先处理：\n"
           f"{format_findings(findings)}\n"
           "处理方式：删除临时文件；把副本合并回原文件；移动到正确目录；或补进 .gitignore。"
           f"如果是用户明确要求保留的，加入 {CONFIG_PATH} 的 allow，并在回复中说明。")
    return emit(agent, "stop", block=msg)


def staged_new_files(root: Path) -> list[str]:
    out = subprocess.run(["git", "-C", str(root), "diff", "--cached", "--name-only", "--diff-filter=AR", "-z"],
                         capture_output=True, check=True)
    return [p for p in out.stdout.decode("utf-8", "replace").split("\0") if p]


def on_pre_commit(root: Path, cfg: Config) -> int:
    """git pre-commit：检查本次提交新增的文件。有问题时退出码 1，git 会中止提交。"""
    findings: list[Finding] = []
    for rel in staged_new_files(root):
        glob = keep_local_match(rel, cfg)
        if glob:
            findings.append(Finding("keep-local-committed", "error", rel, f"按 keepLocal（{glob}）应本地保留、不进 git",
                                    f"git rm --cached {rel!r}，并把该 glob 加进 .gitignore"))
            continue
        art = artifact_dir_of(rel, root)
        if art:
            findings.append(Finding("artifact-committed", "error", art, "依赖 / 生成物被加入提交",
                                    f"git rm -r --cached {art}，并加入 .gitignore"))
            continue
        for f in check_path(rel, cfg):
            if f.rule == "secret-file":
                f.message, f.suggestion = "密钥 / 凭据文件被加入提交", f"git rm --cached {rel!r}，加入 .gitignore；如已推送过，立即轮换密钥"
            findings.append(f)
    findings = apply_config(findings, cfg)
    seen, unique = set(), []
    for f in findings:
        if (f.rule, f.path) not in seen:
            seen.add((f.rule, f.path))
            unique.append(f)
    if not unique:
        return 0
    print(f"[tidy] 提交被拦截：本次新增的文件不符合整洁规范\n{format_findings(unique)}\n"
          f"修正后重新提交。确属有意为之：把路径加入 {CONFIG_PATH} 的 allow，或用 git commit --no-verify 跳过。",
          file=sys.stderr)
    return 1


HANDLERS = {"session-start": on_session_start, "pre-write": on_pre_write, "stop": on_stop}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    event = argv[0] if argv else ""
    explicit = argv[argv.index("--agent") + 1] if "--agent" in argv and argv.index("--agent") + 1 < len(argv) else ""

    if event == "pre-commit":
        try:
            root = git_toplevel(Path.cwd()) or Path.cwd()
            cfg = load_config(root)
            return on_pre_commit(root, cfg) if cfg.hooks else 0
        except Exception as e:  # noqa: BLE001
            print(f"[tidy] pre-commit 检查出错，已放行：{e}", file=sys.stderr)
            return 0

    if event not in HANDLERS:
        print(f"用法：hook.py {{{'|'.join([*HANDLERS, 'pre-commit'])}}} [--agent {'|'.join(AGENTS)}]", file=sys.stderr)
        return 0
    agent = explicit or "claude"
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
        agent = detect_agent(data, explicit)
        root = project_root(data)
        cfg = load_config(root)
        if not cfg.hooks:
            return allow_output(agent, event)
        return HANDLERS[event](data, root, cfg, agent)
    except Exception as e:  # noqa: BLE001 — hook 自身出错时放行，不能卡住用户
        print(f"[tidy] hook 内部错误，已放行：{e}", file=sys.stderr)
        return allow_output(agent, event)


if __name__ == "__main__":
    sys.exit(main())
