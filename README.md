# tidy

让 AI 写的项目保持整洁、可维护的通用 Agent Skill：**文件必要性、目录归属、命名、归档**，不靠 AI 自觉，而是靠机制。

遵循 [Agent Skills 开放标准](https://agentskills.io)，可用于 Claude Code、Codex、Cursor、Gemini CLI、GitHub Copilot、Windsurf 等支持该标准的 Agent；自动检查支持 Claude Code、Codex、Gemini CLI、Cursor，外加对任何工具都有效的 git pre-commit。

## 为什么需要它

AI 写代码时很容易把项目弄乱：

```
.venv/  build/  node_modules/  out/          ← 依赖和生成物没被忽略
提示词分享.md                                 ← 中文文件名，文档散落在根目录
IMPLEMENTATION_SUMMARY.md  test.py           ← 任务报告、临时脚本
src/Root_old.tsx  voice/intro_v2.mp3         ← 版本副本
tools/  voice/                               ← 没人说得清这些目录是干什么的
```

只写一份规范让 AI "注意"是不够的——乱恰恰发生在它埋头干活、没想起规范的时候。所以 tidy 分三层：

| 层 | 做什么 |
|---|---|
| **目录约定** `.tidy.json` | 声明项目里每个目录放什么，所有 Agent 共用。"新文件该放哪"从判断题变成查表题 |
| **自动检查（可选安装）** | ① 会话开始：把规则和目录约定注入给 AI<br>② AI 新建文件前：名字或位置不合规就**拦截**，并告诉它正确做法<br>③ 每轮结束：检查本轮**新增**的文件（包括命令行创建的），有问题就要求先清理再结束<br>④ git 提交前：检查本次提交新增的文件，任何 Agent 和手动提交都适用 |
| **Skill + 脚本** | 判断标准与整理流程；`audit.py` 全面审计、`refs.py` 查引用、`--fix-gitignore` 自动修复、`--init` 生成目录约定；`/tidy` 一键整理 |

自动检查只追究**新增**的文件（包括本轮 `git add` / commit 过的），老项目里已有的问题不会每轮反复提醒——那些用 `/tidy` 一次性整理。核实过、确认没问题的告警可以用 `--review` 记下来，文件不变就不再报告。

## 实际效果

AI 想新建 `src/Title_v2.tsx` 时：

```
[tidy] 拦截新建文件 src/Title_v2.tsx：
- src/Title_v2.tsx：名称带版本 / 副本后缀（v2、new、old、backup、copy、final…）
  → 直接修改原文件，历史交给 git；已有副本则确认当前版本后合并删除
```

AI 用命令行生成了临时脚本、构建产物和 `.env.local`，准备结束时：

```
[tidy] 结束前检查：本轮新增的文件有不符合整洁规范的地方，请先处理：
- check_render.py：疑似临时 / 调试脚本
- dist/：新出现的依赖 / 生成物目录未被忽略
- src/.env.local：密钥 / 凭据文件未被忽略
```

## 安装

需要本机有 `python3`（3.9+）和 git，无第三方依赖。

### 第 1 步：安装 skill（任何 Agent）

用跨 Agent 的安装工具 [`skills`](https://github.com/vercel-labs/skills)（需要 Node.js），它会自动放到你所用 Agent 的 skill 目录：

```bash
npx skills add GaoFei2025-0314/tidy              # 装到当前项目，交互选择 Agent
npx skills add GaoFei2025-0314/tidy -g           # 装到用户目录，对所有项目生效
npx skills add GaoFei2025-0314/tidy -a codex -a claude-code   # 指定 Agent
```

不用 Node.js 的话，把 `skills/tidy` 整个文件夹复制到对应目录即可：

| Agent | 项目级 | 用户级 |
|---|---|---|
| Codex、Cursor、Gemini CLI、GitHub Copilot、Amp 等（通用目录） | `.agents/skills/tidy` | `~/.agents/skills/tidy` |
| Claude Code | `.claude/skills/tidy` | `~/.claude/skills/tidy` |
| 其他 Agent | 见各自文档的 skills 目录 | |

**Claude Code 用户**也可以直接装插件，skill 和自动检查一步到位，可跳过第 2 步：

```
/plugin marketplace add GaoFei2025-0314/tidy
/plugin install tidy@tidy
```

### 第 2 步：开启自动检查（推荐）

在项目根目录运行（`<skill>` 换成第 1 步装好的目录，如 `.agents/skills/tidy`）：

```bash
python3 <skill>/scripts/install.py . --agents codex,cursor,git     # 按你用的工具选
python3 <skill>/scripts/install.py . --agents all                  # claude,codex,gemini,cursor,git 全装
python3 <skill>/scripts/install.py --global --agents codex,gemini  # 写到用户目录，对所有项目生效
python3 <skill>/scripts/install.py . --uninstall --agents all      # 卸载
```

它会与已有配置合并，只增删 tidy 自己的条目，可以重复运行。

| Agent | 写入的配置 | 会话开始注入规则 | 新建文件时拦截 | 结束前检查 |
|---|---|---|---|---|
| Claude Code | `.claude/settings.json` | ✅ | ✅ Write | ✅ Stop |
| Codex | `.codex/hooks.json` | ✅ | ✅ apply_patch | ✅ Stop |
| Gemini CLI | `.gemini/settings.json` | ✅ | ✅ write_file | ✅ AfterAgent |
| Cursor | `.cursor/hooks.json` | ✅ | ✅ Write | ✅ stop（自动追加一条跟进消息） |
| git | `.git/hooks/pre-commit` | — | — | ✅ 提交前，任何工具都有效 |

- **推荐总是装上 `git`**：它不依赖任何 Agent，是最后一道关。
- Codex 首次运行要在 `/hooks` 里信任新 hook；Gemini CLI 会提示确认新 hook；Cursor 只在受信任的工作区运行项目 hook。
- skill 装在项目内时，配置用相对路径，可以提交给团队共用；装在用户目录时写的是本机绝对路径，适合配合 `--global` 使用。

### 让规范常驻（可选）

把 [`skills/tidy/assets/agents-rules.md`](skills/tidy/assets/agents-rules.md) 粘贴进项目的 `AGENTS.md`（Codex、Cursor、Copilot 等都会读）、`CLAUDE.md` 或 `GEMINI.md`。对没有 hooks 的 Agent 尤其有用。

## 使用

### 整理一个已经乱了的项目

在 Agent 里调用 tidy skill：Claude Code 输入 `/tidy`（重名时用 `/tidy:tidy`），其他 Agent 用各自调用 skill 的方式，或直接说「用 tidy 整理一下这个项目」。

它会：扫描 → 查引用 → 给出整理方案表（**停下来等你确认**）→ 用 `git mv` 执行并修复引用 → 跑构建验证 → 生成 `.tidy.json` 目录约定 → 建议你开启自动检查。之后的会话都会自动遵守这份约定。

也可以直接说「帮我整理一下项目」「看看哪些文件是没用的」。

### 单独使用脚本

```bash
S=skills/tidy/scripts
python3 $S/audit.py <项目>                    # 审计报告（同类问题多时折叠，--all 展开）
python3 $S/audit.py <项目> --changed          # 只看相对 HEAD 新增 / 修改的文件（交付前用）
python3 $S/audit.py <项目> --since 2h         # 只看 2 小时内修改的文件（非 git 项目也能用）
python3 $S/audit.py <项目> --review duplicate-file docs/pack/belt.jpg --reason "课包需要独立图片"   # 记录已核实的告警
python3 $S/audit.py <项目> --fail-on error    # CI 中使用，有 error 时退出码 1
python3 $S/audit.py <项目> --init             # 生成 .tidy.json 草稿
python3 $S/audit.py <项目> --fix-gitignore    # 把应忽略的内容补进 .gitignore（只追加）
python3 $S/refs.py  <项目> src/Root_old.tsx   # 这个文件被谁引用？
```

### 目录约定示例

`.tidy.json`（完整字段见 [config.md](skills/tidy/references/config.md)）：

```json
{
  "layout": {
    "src/": "Remotion 源码：compositions/ 每个视频一个文件，components/ 可复用画面组件",
    "public/": "staticFile() 读取的素材：images/、fonts/、audio/",
    "scripts/": "生成配音、批量渲染等脚本",
    "docs/": "文案、提示词、分镜；过时资料放 docs/archive/"
  },
  "allow": { "non-portable-name": ["docs/lessons/**"] },
  "keepLocal": { "out/**": "成片，渲染约 2 小时" },
  "disable": []
}
```

用户明确想要的"例外"（比如学生课包就要中文文件名）按规则加进 `allow`，其他目录仍受检查；成本高、要留在本地但不进 git 的成片、配音、模型登记到 `keepLocal`，审计会要求忽略它们，并且不会建议删除。不想在某个项目启用自动检查，写 `"hooks": false`。旧版的 `.claude/tidy.json` 仍可读取，审计会提示迁移。

### 审计规则

| 规则 | 级别 | 检查内容 | 自动拦截 |
|---|---|---|---|
| `artifact-not-ignored` / `tracked-artifact` | error / warn | 依赖、缓存、生成物目录未忽略或已被跟踪 | 结束前 / 提交前 |
| `secret-tracked` / `secret-not-ignored` | error | `.env`、私钥、凭据文件被跟踪或未忽略（`allow` 不能豁免） | 结束前 / 提交前 |
| `config-invalid` | error | `.tidy.json` 无法解析 | |
| `keep-local-tracked` / `keep-local-not-ignored` | warn | `keepLocal` 登记的文件被跟踪或未忽略 | 结束前 / 提交前 |
| `missing-readme` / `missing-gitignore` | error | 缺少 README 或 .gitignore | |
| `version-suffix` | warn | `*_v2`、`*_old`、`*.backup`、`* copy`、`(1)`、`最终版` 等副本 | ✅ |
| `ai-report-doc` | warn | `docs/` 以外的 `*_SUMMARY.md`、`*_REPORT.md` 等任务报告 | ✅ |
| `scratch-file` | warn | `test.py`、`debug.js` 等临时脚本；`check_*.py` 这类带描述的只在根目录报（测试目录除外） | ✅ |
| `non-portable-name` | warn | 中文、空格、括号等文件名 | ✅ |
| `root-stray-file` | warn | 根目录下的非入口级文件 | ✅ |
| `undeclared-dir` | warn | 文件放在目录约定之外的顶层目录 | ✅ |
| `junk-file` | warn | `.DS_Store`、`*.log`、`*.bak` 等 | ✅ |
| `multiple-lockfiles` / `root-clutter` / `large-file` | warn | 多个 lockfile / 根目录文件过多 / 大文件 | |
| `duplicate-file` / `empty-file` / `empty-dir` | info | 重复（同目录多组合并为一条，跨顶层目录的标为可能的交付副本）、空文件、空目录（只含被忽略文件的不算） | |
| `mixed-naming` | info | 同目录同类文件混用 kebab-case 和 snake_case | |
| `readme-missing-dir` / `layout-missing-dir` / `no-layout` | info | README 或目录约定与实际目录不一致 / 缺少目录约定 | |
| `deep-nesting` / `not-git-repo` | info / warn | 层级过深 / 不是 git 仓库 | |

✅ = 新建文件时直接拦截；命令行创建的由结束前检查兜底；最后还有 git 提交前检查。

## 目录结构

```
.
├── .claude-plugin/            # 插件与 marketplace 清单
├── hooks/hooks.json           # Claude Code 插件的 hooks 声明
├── skills/tidy/               # skill 本体（Agent Skills 标准格式），也是 /tidy 命令
│   ├── SKILL.md               # 判断标准、整理流程、删除 vs 归档
│   ├── references/            # 按需读取的细则：目录结构、必要性、命名、文档、配置
│   ├── scripts/
│   │   ├── rules.py           # 共享规则（自动检查和审计用同一套判断）
│   │   ├── audit.py           # 全面审计、--init、--fix-gitignore
│   │   ├── hook.py            # 自动检查入口：适配各 Agent 的 hook 协议和 git pre-commit
│   │   ├── install.py         # 为各 Agent 安装 / 卸载自动检查
│   │   └── refs.py            # 引用查找
│   └── assets/                # README 模板、.gitignore 片段、AGENTS.md 规则片段
├── .tidy.json                 # 本仓库自己的目录约定
├── tests/                     # 单元测试（含各 Agent hook 协议测试）
└── .github/workflows/         # CI：跑测试，并用本插件审计本仓库
```

## 开发

```bash
python3 -m unittest discover -s tests -v
```

## License

MIT
