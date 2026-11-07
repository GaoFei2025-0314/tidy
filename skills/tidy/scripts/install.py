#!/usr/bin/env python3
"""为各个 Agent 安装 / 卸载 tidy 的自动检查（hooks）和 git pre-commit 检查。

用法:
    python3 install.py [项目路径] --agents claude,codex,gemini,cursor,git
    python3 install.py [项目路径] --agents all
    python3 install.py --global --agents codex,gemini       # 写到用户目录，对所有项目生效
    python3 install.py [项目路径] --uninstall --agents all

会与已有配置合并，只增删 tidy 自己的条目，可以重复运行。只依赖 Python 标准库。
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parent / "hook.py"
MARKER = "tidy/scripts/hook.py"  # 识别 tidy 自己写入的条目
ALL = ["claude", "codex", "gemini", "cursor", "git"]

# 各 Agent：项目级配置文件、用户级配置文件、事件 → (hook.py 子命令, matcher)
SPECS = {
    "claude": (".claude/settings.json", "~/.claude/settings.json", {
        "SessionStart": ("session-start", None),
        "PreToolUse": ("pre-write", "Write"),
        "Stop": ("stop", None),
    }),
    "codex": (".codex/hooks.json", "~/.codex/hooks.json", {
        "SessionStart": ("session-start", None),
        "PreToolUse": ("pre-write", "apply_patch|Write"),
        "Stop": ("stop", None),
    }),
    "gemini": (".gemini/settings.json", "~/.gemini/settings.json", {
        "SessionStart": ("session-start", None),
        "BeforeTool": ("pre-write", "write_file"),
        "AfterAgent": ("stop", None),
    }),
    "cursor": (".cursor/hooks.json", "~/.cursor/hooks.json", {
        "sessionStart": ("session-start", None),
        "preToolUse": ("pre-write", "Write"),
        "stop": ("stop", None),
    }),
}
NOTES = {
    "codex": "Codex 首次运行会要求审核新 hook：在 Codex 里输入 /hooks 信任它们。",
    "gemini": "Gemini CLI 会对新的项目 hook 给出提示，确认即可；可用 /hooks panel 查看。",
    "cursor": "Cursor 只在受信任的工作区运行项目 hook。",
}


def hook_command(agent: str, event: str, project: Path | None) -> str:
    """生成调用 hook.py 的命令。skill 装在项目内时用相对路径，团队成员可以共用同一份配置。"""
    rel = None
    if project is not None:
        try:
            rel = HOOK.relative_to(project).as_posix()
        except ValueError:
            rel = None
    if rel is None:
        script = f'"{HOOK.as_posix()}"'
    elif agent == "claude":
        script = f'"$CLAUDE_PROJECT_DIR/{rel}"'
    elif agent == "gemini":
        script = f'"$GEMINI_PROJECT_DIR/{rel}"'
    elif agent == "codex":
        script = f'"$(git rev-parse --show-toplevel)/{rel}"'
    else:  # cursor 项目 hook、git hook 都从项目根目录运行
        script = f'"{rel}"'
    tail = f" --agent {agent}" if agent != "git" else ""
    return f"python3 {script} {event}{tail}"


def load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return {}
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"{path} 顶层不是 JSON 对象，未修改")
    return data


def is_ours(handler: dict) -> bool:
    return MARKER in str(handler.get("command", ""))


def strip_ours(hooks: dict, agent: str) -> None:
    """从 hooks 配置中移除 tidy 的条目，保留其他工具的。"""
    for event in list(hooks):
        groups = hooks[event]
        if not isinstance(groups, list):
            continue
        kept = []
        for g in groups:
            if not isinstance(g, dict):
                kept.append(g)
            elif agent == "cursor":
                if not is_ours(g):
                    kept.append(g)
            else:
                inner = [h for h in g.get("hooks", []) if not (isinstance(h, dict) and is_ours(h))]
                if inner or not g.get("hooks"):
                    kept.append({**g, "hooks": inner} if "hooks" in g else g)
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]


def install_agent(agent: str, project: Path | None, uninstall: bool) -> str:
    proj_rel, user_path, events = SPECS[agent]
    path = Path(os.path.expanduser(user_path)) if project is None else project / proj_rel
    data = load_json(path)
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError(f"{path} 的 hooks 字段不是对象，未修改")
    strip_ours(hooks, agent)
    if not uninstall:
        for event, (sub, matcher) in events.items():
            cmd = hook_command(agent, sub, project)
            if agent == "cursor":
                entry: dict = {"command": cmd, "timeout": 20}
                if matcher:
                    entry["matcher"] = matcher
            else:
                handler = {"type": "command", "command": cmd,
                           # Gemini 的 timeout 单位是毫秒，其他是秒
                           "timeout": 20000 if agent == "gemini" else 20}
                if agent == "gemini":
                    handler["name"] = f"tidy-{sub}"
                entry = {"hooks": [handler]}
                if matcher:
                    entry["matcher"] = matcher
            hooks.setdefault(event, []).append(entry)
        if agent == "cursor":
            data.setdefault("version", 1)
    if not hooks:
        del data["hooks"]
    if uninstall and not path.exists():
        return f"{agent}: 未安装，跳过"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return f"{agent}: {'已卸载' if uninstall else '已写入'} {path}"


GIT_HOOK = """#!/bin/sh
# tidy pre-commit：检查本次提交新增的文件（{marker}）
{command}
"""


def install_git(project: Path, uninstall: bool) -> str:
    try:
        hooks_dir = subprocess.run(["git", "-C", str(project), "rev-parse", "--git-path", "hooks"],
                                   capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "git: 不是 git 仓库，跳过"
    path = (project / hooks_dir).resolve() / "pre-commit"
    existing = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    if existing and MARKER not in existing:
        return (f"git: {path} 已有其他 pre-commit hook，未覆盖。请在其中加一行：\n"
                f"     {hook_command('git', 'pre-commit', project)} || exit 1")
    if uninstall:
        if existing:
            path.unlink()
            return f"git: 已删除 {path}"
        return "git: 未安装，跳过"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(GIT_HOOK.format(marker=MARKER, command=hook_command("git", "pre-commit", project)),
                    encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return f"git: {'已更新' if existing else '已写入'} {path}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="为各个 Agent 安装 tidy 的自动检查")
    ap.add_argument("path", nargs="?", default=".", help="项目根目录，默认当前目录")
    ap.add_argument("--agents", required=True, help=f"逗号分隔：{','.join(ALL)}，或 all")
    ap.add_argument("--global", dest="global_", action="store_true", help="写到用户目录，对所有项目生效（不含 git）")
    ap.add_argument("--uninstall", action="store_true", help="移除 tidy 的条目")
    args = ap.parse_args(argv)

    agents = ALL if args.agents.strip() == "all" else [a.strip() for a in args.agents.split(",") if a.strip()]
    unknown = [a for a in agents if a not in ALL]
    if unknown:
        print(f"未知的 Agent：{', '.join(unknown)}（可选：{', '.join(ALL)}）", file=sys.stderr)
        return 2
    project = None if args.global_ else Path(args.path).resolve()
    if project is not None and not project.is_dir():
        print(f"不是目录：{project}", file=sys.stderr)
        return 2

    failed = False
    for agent in agents:
        try:
            if agent == "git":
                msg = "git: --global 模式不支持，跳过" if project is None else install_git(project, args.uninstall)
            else:
                msg = install_agent(agent, project, args.uninstall)
        except (OSError, ValueError) as e:
            msg, failed = f"{agent}: 失败 —— {e}", True
        print(msg)
        if not args.uninstall and agent in NOTES and "已写入" in msg:
            print(f"     {NOTES[agent]}")
    if project is not None and not args.uninstall:
        try:
            HOOK.relative_to(project)
        except ValueError:
            print("\n提示：skill 不在项目目录内，配置里写的是本机绝对路径，提交给团队前请改用项目内安装的 skill。")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
