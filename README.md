# project-hygiene

一个 Claude Code / Agent Skill，用来规范 AI 生成项目的**整洁度和可维护性**：

- **文件必要性**——每个文件都要说得清为什么存在，临时脚本、`*_v2` 副本、AI 任务报告不落进仓库；
- **文件归属**——根目录只放入口级文件，源码、素材、脚本、文档、生成物各归其位；
- **命名与可读性**——ASCII、风格一致、名字说明用途；
- **归档**——什么该删、什么该忽略、什么进 `docs/archive/`，有明确的决策规则；
- **审计脚本**——只读扫描项目，列出问题和处理建议，可用于 CI。

## 它解决什么问题

AI 写代码时很容易把项目弄乱：

```
.venv/  build/  node_modules/  out/          ← 依赖和生成物没被忽略
提示词分享.md                                 ← 中文文件名，文档散落在根目录
IMPLEMENTATION_SUMMARY.md  test.py           ← 任务报告、临时脚本
src/Root_old.tsx  voice/intro_v2.mp3         ← 版本副本
tools/  voice/                               ← README 没说这些目录是干什么的
```

装上这个 skill 后，Claude 会在**新建文件前**按规范判断该不该建、放哪、叫什么；在**任务结束时**自检；在你说「帮我整理一下项目」时，先审计、出方案、经你确认后再用 `git mv` 执行并修复引用。

## 安装

### 方式一：作为 Claude Code 插件（推荐）

```
/plugin marketplace add <你的 GitHub 用户名>/project-hygiene-skill
/plugin install project-hygiene@project-hygiene
```

### 方式二：直接复制 skill 目录

```bash
# 对所有项目生效
cp -r skills/project-hygiene ~/.claude/skills/

# 只对某个项目生效
cp -r skills/project-hygiene <你的项目>/.claude/skills/
```

### 让规范长期生效

Skill 只在相关任务时触发。想让项目里每次 AI 改动都遵守，把 [`skills/project-hygiene/assets/agents-rules.md`](skills/project-hygiene/assets/agents-rules.md) 的内容粘贴进项目的 `CLAUDE.md` 或 `AGENTS.md`。

## 使用

在 Claude Code 里直接说：

- 「帮我整理一下这个项目的文件结构」
- 「这个仓库太乱了，看看哪些文件是没用的」
- 「检查一下项目规范」

也可以单独运行审计脚本（Python 3.9+，无第三方依赖）：

```bash
python3 skills/project-hygiene/scripts/audit.py <项目路径>
python3 skills/project-hygiene/scripts/audit.py <项目路径> --format json
python3 skills/project-hygiene/scripts/audit.py <项目路径> --fail-on error   # CI 中使用
```

### 审计规则

| 规则 | 级别 | 检查内容 |
|---|---|---|
| `missing-readme` / `missing-gitignore` | error | 缺少 README 或 .gitignore |
| `artifact-not-ignored` | error / warn | `node_modules`、`.venv`、`__pycache__` 等未忽略（error）；`build`、`dist`、`out` 未忽略（warn） |
| `tracked-artifact` | error / warn | 依赖 / 生成物已被 git 跟踪 |
| `secret-tracked` / `secret-not-ignored` | error | `.env`、私钥、凭据文件被跟踪或未忽略 |
| `not-git-repo` | warn | 不是 git 仓库，整理操作无法回滚 |
| `multiple-lockfiles` | warn | 同时存在多个包管理器的 lockfile |
| `root-stray-file` / `root-clutter` | warn | 根目录有非入口级文件 / 文件过多 |
| `version-suffix` | warn | `*_v2`、`*_old`、`*.backup`、`* copy`、`(1)`、`最终版` 等副本 |
| `ai-report-doc` | warn | `*_SUMMARY.md`、`*_REPORT.md` 等任务报告 |
| `scratch-file` | warn | `test.py`、`debug.js`、`tmp.ts` 等临时脚本 |
| `junk-file` | warn | `.DS_Store`、`*.log`、`*.bak` 等 |
| `non-portable-name` | warn | 中文、空格、括号等文件名 |
| `large-file` | warn | 超过 5 MB 的文件（`--large-mb` 可调） |
| `duplicate-file` | info | 内容完全相同的文件 |
| `empty-file` / `empty-dir` | info | 空文件、空目录 |
| `mixed-naming` | info | 同目录同类文件混用 kebab-case 和 snake_case |
| `readme-missing-dir` | info | README 没有提到的顶层目录 |
| `deep-nesting` | info | 目录层级过深 |

脚本是启发式检查，只读不改。真正删除或移动之前，skill 会要求 Claude 先确认文件没有被引用，并征得你的同意。

## 目录结构

```
.
├── .claude-plugin/            # Claude Code 插件与 marketplace 清单
├── skills/project-hygiene/    # skill 本体
│   ├── SKILL.md               # 主说明：守则、整理流程、删除 vs 归档
│   ├── references/            # 按需读取的细则：目录结构、必要性、命名、文档
│   ├── scripts/audit.py       # 只读审计脚本
│   └── assets/                # README 模板、.gitignore 片段、CLAUDE.md 规则片段
├── tests/                     # 审计脚本的单元测试
└── .github/workflows/         # CI：跑测试，并用本 skill 审计本仓库
```

## 开发

```bash
python3 -m unittest discover -s tests -v
```

## License

MIT
