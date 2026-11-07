---
name: tidy
description: 规范 AI 生成项目的文件整洁度与可维护性——判断每个文件是否必要、应该放在哪、该删除还是归档，保持根目录干净、命名一致、目录约定清楚。Use when creating or scaffolding a project, before creating any new file (scratch/debug scripts, summary reports, *_v2 / *_backup copies, generated outputs), when a tidy check blocks a file or flags new files, when finishing a coding task, or when the user asks to 整理 / 清理 / 规范 / 归档 a project, says the repo is messy (项目太乱、文件太多、看不懂、不知道哪些文件有用), or asks for a project structure audit.
license: MIT
compatibility: Scripts need Python 3.9+ (standard library only) and git. Optional automatic checks support Claude Code, Codex, Gemini CLI, Cursor and git pre-commit.
metadata:
  author: GAOFEI
  version: "0.3.0"
---

# Tidy · 项目整洁规范

仓库里的每个文件都必须能回答三个问题：

1. **为什么存在？**（必要性）——删掉它会坏掉什么？
2. **为什么在这里？**（归属）——按本项目的目录约定，它属于哪个目录？
3. **别人看得懂吗？**（可读性）——只看文件名和 README，新人能猜到它是干什么的吗？

> 用户输入 `/tidy`（或在你的工具里调用 tidy skill）时，直接执行下文「模式二：整理已有项目」。
>
> 下文的 `<skill>` 指本 skill 所在的目录，脚本只依赖 Python 3.9+ 标准库。

## 三层机制

| 层 | 作用 | 由谁执行 |
|---|---|---|
| **目录约定** `.tidy.json` | 声明每个顶层目录放什么，把"该放哪"从判断变成查表 | 你在整理项目时生成，之后长期维护 |
| **自动检查**（可选，见「安装自动检查」） | 会话开始注入规则和目录约定；拦截不合规的新文件；每轮结束检查新增文件；git 提交前检查新增文件 | 自动，见下文「收到自动检查的提示时」 |
| **本 skill** | 写代码时的判断标准、整理老项目的流程 | 你 |

自动检查只管**新增**的文件，老项目已有的问题由「模式二」整理。

### 三种检查粒度

| 时机 | 做什么 |
|---|---|
| 新建文件时 | 过一遍下面的 4 问（装了自动检查时会自动拦截） |
| 阶段交付 / 任务结束 | `audit.py <根目录> --changed`（git 项目，只看相对 HEAD 的变化）或 `--since 2h`（按修改时间，非 git 项目也能用）。**没装自动检查的 Agent，每次交付前都跑一次。** |
| 用户要求整理项目 | 全量 `audit.py <根目录>`，走「模式二」 |

核实后确认无需处理的告警（有意的交付副本、第三方文件名），用 `audit.py <根目录> --review <规则> <路径> --reason <结论>` 记下来，之后不再报告；文件内容变化后会重新出现，提醒你复核。

---

## 模式一：写代码时（每次都适用）

### 新建文件前的 4 问

| 问题 | 不通过时怎么做 |
|---|---|
| **必要吗？** 能否写进已有文件？是否只是一次性的？ | 合并进已有文件；一次性内容写在回复里，不落盘 |
| **放哪？** 符合 `.tidy.json` 的 layout 吗？ | 放进已声明的目录；确需新顶层目录时，先在 layout 和 README「目录结构」登记 |
| **叫什么？** 名字能说明用途、和同目录风格一致吗？ | 按 [references/naming.md](references/naming.md) 命名 |
| **该提交吗？** 是生成物、依赖、密钥、大文件吗？ | 加进 `.gitignore`，不进版本库 |

### AI 最常见的坏习惯（禁止）

| ❌ 坏习惯 | ✅ 正确做法 |
|---|---|
| 在根目录写 `test.py`、`debug.js`、`check_xxx.py` 临时脚本 | 写到 `.scratch/`（确保已忽略）或系统临时目录，任务结束即删 |
| 复制出 `foo_v2.ts`、`foo_new.ts`、`foo.backup.ts`、`foo_old/` | 直接改原文件，历史交给 git |
| 每做完一件事就生成 `IMPLEMENTATION_SUMMARY.md`、`FIX_REPORT.md` | 总结写在回复和 commit message 里；长期知识合并进 README 或 `docs/` 已有文档 |
| 提交 `build/`、`out/`、`dist/`、渲染出的视频音频、日志 | 加进 `.gitignore`；README 写清楚怎么生成 |
| `node_modules/`、`.venv/` 被提交或散落各处 | 忽略；多语言工具链各自归位（见 structure.md「混合项目」） |
| 中文、空格、括号文件名：`提示词分享.md`、`final (1).mp4` | 文件名用英文 kebab-case，中文写进文件标题 |
| 脚手架样板没清理、大段注释掉的旧代码、没用上的依赖 | 确认无引用后删除 |
| 同一配置写两份（`.prettierrc` + `package.json#prettier`） | 只保留一处 |
| 为了"以后可能用"预先建空目录、空文件 | 用到时再建 |

### 收到自动检查的提示时

- **新建文件被拦截**：按提示换做法——合并进已有文件、换目录、换名字，或者干脆不落盘。**不要**为了绕过拦截改用命令行写文件（结束前检查和 git 提交检查照样会发现）。
- **结束前检查列出了问题**：逐条处理（删除临时文件、合并副本、移动、补 `.gitignore`），处理完再结束。
- **用户明确要求这样做**（比如就要一个中文文件名）：按规则把路径加进 `.tidy.json` 的 `allow`（如 `{"non-portable-name": ["docs/课程/**"]}`），并在回复中说明。豁免范围尽量小，不要用 `disable` 关掉整条规则，也不要自作主张加豁免。
- **本地要保留、但不该进 git 的文件**（成片、已验收配音、模型权重等）：登记到 `keepLocal` 并写明原因，再补 `.gitignore`。不要删除。
- **需要新的顶层目录**：先确认确实没有合适的已有目录，再在 `layout` 和 README「目录结构」中登记。

---

## 模式二：整理已有项目

脚本都在本 skill 的 `scripts/` 目录下，只依赖 Python 3.9+ 标准库。

### 第 1 步：扫描

```bash
python3 <skill>/scripts/audit.py <项目根目录>            # 文本报告
python3 <skill>/scripts/audit.py <项目根目录> --format json
```

### 第 2 步：理解项目，查引用

脚本是启发式的，每条告警都要核实后再处理。文本报告会折叠数量多的同类问题，需要逐条查看时加 `--all`。下结论前：

- 读 README、`package.json` / `pyproject.toml` 的 scripts 和入口；
- 对每个想删除或移动的文件查引用：

  ```bash
  python3 <skill>/scripts/refs.py <项目根目录> <文件> [<文件> ...]
  ```

  结论分四种：`in-use`（有明确引用）、`convention`（框架按约定加载）、`maybe`（只有弱匹配）、`unreferenced`（没找到）。**`unreferenced` 也要考虑动态路径和外部调用**，判断标准见 [references/file-necessity.md](references/file-necessity.md)。

### 第 3 步：给出整理方案，等待确认

| 路径 | 动作 | 目标位置 | 理由 |
|---|---|---|---|
| `提示词分享.md` | 移动+重命名 | `docs/prompts.md` | 根目录散落文档；非 ASCII 文件名 |
| `out/` | 忽略 | — | 渲染产物，可由 `npm run render` 重新生成 |
| `src/Root_old.tsx` | 删除 | — | refs.py：unreferenced；内容与 Root.tsx 相同 |

动作只有七种：**保留 / 移动 / 重命名 / 删除 / 归档 / 忽略 / 本地保留**（忽略但不删除，登记到 `keepLocal`）。拿不准的标「待确认」。告警属于预期情况（交付副本、连续截帧）时，动作是按规则加 `allow`，而不是删文件。

**删除和批量移动必须先得到用户确认。** 方案确认前不要动文件。

### 第 4 步：执行

1. 确保工作区干净；不是 git 仓库就先建议 `git init` 并做一次初始提交作为快照。
2. `python3 <skill>/scripts/audit.py <根目录> --fix-gitignore`：自动把未忽略的依赖、生成物、垃圾文件、密钥补进 `.gitignore`（只追加，不删除）。已被 git 跟踪的会列出来，需要 `git rm --cached`。
3. 移动 / 重命名用 `git mv`；之后对旧路径运行 refs.py 或 grep，修复所有引用（import、`staticFile()`、配置、脚本、文档链接）。
4. 跑构建 / 测试 / lint，确认没有被破坏。
5. 结构调整和代码修改**分开提交**。

### 第 5 步：固化目录约定（不要跳过）

整理完后，生成目录约定，让以后的每个会话自动遵守：

```bash
python3 <skill>/scripts/audit.py <根目录> --init     # 按现有顶层目录生成 .tidy.json 草稿
```

然后补全每个目录的说明（替换 `TODO`），写法要能指导放置决策，例如 `"public/": "staticFile() 读取的素材：图片、字体、配音"`，而不是只写"静态资源"。同步更新 README「目录结构」。配置格式见 [references/config.md](references/config.md)。

最后建议用户安装自动检查（见下节），让规范在以后的每次改动中自动生效。

### 安装自动检查

用户要求开启自动检查，或整理完项目后用户同意时，运行：

```bash
python3 <skill>/scripts/install.py <项目根目录> --agents claude,codex,gemini,cursor,git   # 按用户实际使用的工具选
python3 <skill>/scripts/install.py <项目根目录> --uninstall --agents all                  # 卸载
```

它会与已有配置合并，只增删 tidy 自己的条目，可以重复运行。`git` 是 pre-commit 检查，对任何 Agent 和手动提交都有效，**推荐总是装上**。装完提醒用户：Codex 要在 `/hooks` 里信任新 hook，Cursor 要信任工作区。

### 安全底线

- **不可再生的文件**（用户素材、录音、手写提示词、数据）未经确认绝不删除——移到合适目录或归档。
- 不读取、不输出 `.env` 等密钥内容；若发现密钥已被 git 跟踪，提醒用户**轮换密钥**并清理历史，而不只是删除文件。
- 不确定一个文件是否在用时，标记为「待确认」，不要猜。

---

## 删除还是归档？

```
「是否进 git」和「是否删除」分开判断。

这个文件……
├─ 能低成本重新生成吗？（构建产物、缓存、日志、依赖、临时取帧）
│    └─ 是 → 删除 + 加进 .gitignore
├─ 能重新生成，但成本高？（成片、已验收配音、渲染好的课包、训练好的模型——要花时间、费用或重新验收）
│    └─ 是 → 本地保留 + 加进 .gitignore + 登记到 tidy.json 的 keepLocal（写明原因），README 写明生成方式
├─ 是已被 git 跟踪的过时代码吗？
│    └─ 是 → 直接删除（git 历史就是归档）
├─ 不可再生，且仍有参考价值？（调研笔记、旧提示词、设计稿、决策记录）
│    └─ 是 → 移到 docs/archive/，文件名加日期前缀，在 docs/archive/README.md 记一行原因
├─ 是大体积素材？（音视频、数据集、模型）
│    └─ 是 → 不进 git（或用 Git LFS），README 写明获取方式
└─ 不可再生，也没有价值 → 列出来，用户确认后删除
```

归档细则见 [references/docs.md](references/docs.md)。

## 参考文件

| 文件 | 内容 | 何时读 |
|---|---|---|
| [references/structure.md](references/structure.md) | 根目录白名单、各类项目的标准目录布局（Node/TS、Remotion、Python、混合项目） | 决定文件放哪、设计 layout |
| [references/file-necessity.md](references/file-necessity.md) | 判断文件是否必要、常见可删样板 | 判断能不能删 |
| [references/naming.md](references/naming.md) | 各语言命名约定、禁止的命名模式 | 新建或重命名文件 |
| [references/docs.md](references/docs.md) | README 最低要求、docs/ 布局、归档规则 | 写文档、归档 |
| [references/config.md](references/config.md) | `.tidy.json` 字段说明与示例 | 生成或修改目录约定 |
| [assets/README.template.md](assets/README.template.md) | README 模板 | 项目缺 README |
| [assets/gitignore/](assets/gitignore/) | `.gitignore` 片段：通用、Node、Python、媒体 | 补全忽略规则 |
| [assets/agents-rules.md](assets/agents-rules.md) | 可粘贴进 AGENTS.md / CLAUDE.md / GEMINI.md 的常驻规则 | 项目要让任何 Agent 始终遵守规范 |
