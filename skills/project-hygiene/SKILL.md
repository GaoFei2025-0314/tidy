---
name: project-hygiene
description: 规范 AI 生成项目的文件整洁度与可维护性——判断每个文件是否必要、应该放在哪、该删除还是归档，保持根目录干净、命名一致、README 能说明每个目录的用途。Use when creating or scaffolding a project, before creating any new file (scratch/debug scripts, summary reports, *_v2 / *_backup copies, generated outputs), when finishing a coding task (pre-commit cleanup), or when the user asks to 整理 / 清理 / 规范 / 归档 a project, says the repo is messy (项目太乱、文件太多、看不懂、不知道哪些文件有用), or asks for a project structure audit.
---

# Project Hygiene · 项目整洁规范

仓库里的每个文件都必须能回答三个问题：

1. **为什么存在？**（必要性）——删掉它会坏掉什么？
2. **为什么在这里？**（归属）——按目录约定，它属于哪一层？
3. **别人看得懂吗？**（可读性）——只看文件名和 README，新人能猜到它是干什么的吗？

答不上来的文件就是维护负担。本 skill 有两种用法：**写代码时的守则**（预防）和**整理已有项目**（治理）。

---

## 模式一：写代码时的守则（每次都适用）

### 新建文件前的 4 问

在调用 Write / 新建任何文件之前，先过一遍：

| 问题 | 不通过时怎么做 |
|---|---|
| **必要吗？** 能否写进已有文件？是否只是一次性的？ | 合并进已有文件；一次性内容写在回复里，不落盘 |
| **放哪？** 符合项目已有的目录约定吗？ | 按 [references/structure.md](references/structure.md) 放到对应目录，不要放根目录 |
| **叫什么？** 名字能说明用途、和同目录风格一致吗？ | 按 [references/naming.md](references/naming.md) 命名 |
| **该提交吗？** 是生成物、依赖、密钥、大文件吗？ | 加进 `.gitignore`，不进版本库 |

### AI 最常见的坏习惯（禁止）

| ❌ 坏习惯 | ✅ 正确做法 |
|---|---|
| 在根目录写 `test.py`、`debug.js`、`check_xxx.py` 临时脚本 | 写到系统临时目录或已忽略的 `.scratch/`，任务结束即删 |
| 复制出 `foo_v2.ts`、`foo_new.ts`、`foo.backup.ts`、`foo_old/` | 直接改原文件，历史交给 git |
| 每做完一件事就生成 `IMPLEMENTATION_SUMMARY.md`、`FIX_REPORT.md`、`CHANGES_xxx.md` | 总结写在回复和 commit message 里；有长期价值的知识合并进 README 或 `docs/` 已有文档 |
| 提交 `build/`、`out/`、`dist/`、渲染出的视频音频、日志 | 加进 `.gitignore`；README 写清楚怎么生成 |
| `node_modules/`、`.venv/` 被提交或散落各处 | 忽略；多语言工具链各自归位（见 structure.md「混合项目」） |
| 中文、空格、括号文件名：`提示词分享.md`、`final (1).mp4` | 文件名用英文 kebab-case，中文写进文件标题 |
| 脚手架样板没清理（未使用的 `logo.svg`、示例组件、空测试） | 确认没有引用后删除 |
| 大段注释掉的旧代码 | 直接删除 |
| 同一配置写两份（`.prettierrc` + `package.json#prettier`） | 只保留一处 |
| 为了"以后可能用"预先建空目录、空文件 | 用到时再建 |
| 引入依赖但没用上 / 删了代码但依赖还在 | 同步清理 `package.json` / `requirements.txt` |

### 任务收尾检查（每次完成编码任务、提交之前）

1. 看 `git status`，逐个审视**新增**文件，过一遍「4 问」。
2. 删除本次任务产生的临时文件、调试输出。
3. 如果新增了顶层目录或改变了结构，同步更新 README 的「目录结构」。
4. 新出现的生成物 / 缓存目录，补进 `.gitignore`。
5. 可选：运行审计脚本做一次快速自检（见下）。

---

## 模式二：整理已有项目

### 第 1 步：扫描

```bash
python3 <本 skill 目录>/scripts/audit.py <项目根目录>
# 机器可读：--format json；用于 CI：--fail-on error
```

脚本只用 Python 标准库，会检查：生成物/依赖未忽略、已被 git 跟踪的产物、版本后缀副本、AI 报告类文档、根目录杂乱、非 ASCII/空格文件名、大文件、密钥文件、重复文件、空文件/空目录、README 未说明的顶层目录、命名风格混用、多个 lockfile 等。

### 第 2 步：理解项目（不能只信脚本）

脚本是启发式的。下结论前必须：

- 读 README、`package.json` / `pyproject.toml` 的 scripts 和入口；
- 对每个"疑似无用"文件，**grep 它的文件名和模块名**，检查 import、配置、脚本、文档中是否被引用；
- 判断标准见 [references/file-necessity.md](references/file-necessity.md)。

### 第 3 步：给出整理方案，等待确认

用一张表列出每个要动的文件/目录：

| 路径 | 动作 | 目标位置 | 理由 |
|---|---|---|---|
| `提示词分享.md` | 移动+重命名 | `docs/prompts.md` | 根目录散落文档；非 ASCII 文件名 |
| `out/` | 忽略 | — | 渲染产物，可由 `npm run render` 重新生成 |

动作只有六种：**保留 / 移动 / 重命名 / 删除 / 归档 / 忽略**。

**删除和批量移动必须先得到用户确认。** 方案未确认前不要动文件。

### 第 4 步：执行

- 先确保工作区干净；不是 git 仓库就先建议 `git init` 并做一次初始提交作为快照。
- 移动/重命名用 `git mv`，保留历史。
- 移动后 **grep 旧路径**，修复所有引用（import、`require`、`staticFile()`、配置文件、脚本、文档链接）。
- 跑构建 / 测试 / lint 验证没有被破坏。
- 更新 README「目录结构」，补全 `.gitignore`（模板在 `assets/gitignore/`）。
- 结构调整和代码修改**分开提交**，提交信息说明移动了什么、为什么。

### 安全底线

- **不可再生的文件**（用户素材、录音、手写提示词、数据）未经确认绝不删除——移到合适目录或归档。
- 不读取、不输出 `.env` 等密钥内容；若发现密钥已被 git 跟踪，提醒用户**轮换密钥**并从历史中清除，而不只是删除文件。
- 不确定一个文件是否在用时，标记为「待确认」，不要猜。

---

## 删除还是归档？

```
这个文件……
├─ 能重新生成吗？（构建产物、缓存、日志、依赖、渲染输出）
│    └─ 是 → 删除 + 加进 .gitignore
├─ 是已被 git 跟踪的过时代码吗？
│    └─ 是 → 直接删除（git 历史就是归档）
├─ 不可再生，且仍有参考价值？（调研笔记、旧提示词、设计稿、决策记录）
│    └─ 是 → 移到 docs/archive/，文件名加日期前缀，在 docs/archive/README.md 记一行原因
├─ 是大体积素材？（音视频、数据集、模型）
│    └─ 是 → 不进 git（或用 Git LFS），README 写明获取方式
└─ 不可再生，也没有价值 → 列出来，用户确认后删除
```

归档细则与文档规范见 [references/docs.md](references/docs.md)。

---

## 让规范长期生效

Skill 只在触发时生效。要让项目里每次 AI 改动都遵守，把 [assets/agents-rules.md](assets/agents-rules.md) 的内容复制进项目的 `CLAUDE.md` 或 `AGENTS.md`。整理完一个项目后，主动建议用户这样做。

## 参考文件

| 文件 | 内容 | 何时读 |
|---|---|---|
| [references/structure.md](references/structure.md) | 根目录白名单、各类项目的标准目录布局（Node/TS、Remotion、Python、混合项目） | 决定文件放哪 |
| [references/file-necessity.md](references/file-necessity.md) | 判断文件是否必要、如何验证无引用、常见可删样板 | 判断能不能删 |
| [references/naming.md](references/naming.md) | 各语言命名约定、禁止的命名模式 | 新建或重命名文件 |
| [references/docs.md](references/docs.md) | README 最低要求、docs/ 布局、归档规则 | 写文档、归档 |
| [assets/README.template.md](assets/README.template.md) | README 模板 | 项目缺 README |
| [assets/gitignore/](assets/gitignore/) | `.gitignore` 片段：通用、Node、Python、媒体 | 补全忽略规则 |
| [assets/agents-rules.md](assets/agents-rules.md) | 可粘贴进 CLAUDE.md / AGENTS.md 的规则 | 让规范长期生效 |
