# tidy

让 AI 写的项目保持整洁、可维护的 Claude Code 插件：**文件必要性、目录归属、命名、归档**，不靠 AI 自觉，而是靠机制。

## 为什么需要它

AI 写代码时很容易把项目弄乱：

```
.venv/  build/  node_modules/  out/          ← 依赖和生成物没被忽略
提示词分享.md                                 ← 中文文件名，文档散落在根目录
IMPLEMENTATION_SUMMARY.md  test.py           ← 任务报告、临时脚本
src/Root_old.tsx  voice/intro_v2.mp3         ← 版本副本
tools/  voice/                               ← 没人说得清这些目录是干什么的
```

只写一份规范让 AI "注意"是不够的——乱恰恰发生在它埋头干活、没想起规范的时候。所以这个插件分三层：

| 层 | 做什么 |
|---|---|
| **目录约定** `.claude/tidy.json` | 声明项目里每个目录放什么。"新文件该放哪"从判断题变成查表题 |
| **Hooks（自动执行）** | ① 会话开始：把规则和目录约定注入给 AI<br>② AI 新建文件前：名字或位置不合规就**拦截**，并告诉它正确做法<br>③ 每轮结束：检查本轮**新增**的文件（包括用 Bash 创建的），有问题就要求先清理再结束 |
| **Skill + 脚本** | 判断标准与整理流程；`audit.py` 全面审计、`refs.py` 查引用、`--fix-gitignore` 自动修复、`--init` 生成目录约定；`/tidy` 一键整理 |

Hooks 只追究**新增**的文件（包括本轮 `git add` / commit 过的），老项目里已有的问题不会每轮反复提醒——那些用 `/tidy` 一次性整理。核实过、确认没问题的告警可以用 `--review` 记下来，文件不变就不再报告。

## 实际效果

AI 想新建 `src/Title_v2.tsx` 时：

```
[tidy] 拦截新建文件 src/Title_v2.tsx：
- src/Title_v2.tsx：名称带版本 / 副本后缀（v2、new、old、backup、copy、final…）
  → 直接修改原文件，历史交给 git；已有副本则确认当前版本后合并删除
```

AI 用 Bash 生成了临时脚本、构建产物和 `.env.local`，准备结束时：

```
[tidy] 结束前检查：本轮新增的文件有不符合整洁规范的地方，请先处理：
- check_render.py：疑似临时 / 调试脚本
- dist/：新出现的依赖 / 生成物目录未被忽略
- src/.env.local：密钥 / 凭据文件未被忽略
```

## 安装

### 方式一：Claude Code 插件（推荐，包含 hooks）

```
/plugin marketplace add GaoFei2025-0314/tidy
/plugin install tidy@tidy
```

需要本机有 `python3`（3.9+），无第三方依赖。

### 方式二：只装 skill + 手动配置 hooks

```bash
cp -r skills/tidy ~/.claude/skills/
```

然后在 `~/.claude/settings.json`（全局）或项目的 `.claude/settings.json` 中加入：

```json
{
  "hooks": {
    "SessionStart": [{ "hooks": [{ "type": "command", "command": "python3 ~/.claude/skills/tidy/scripts/hook.py session-start" }] }],
    "PreToolUse": [{ "matcher": "Write", "hooks": [{ "type": "command", "command": "python3 ~/.claude/skills/tidy/scripts/hook.py pre-write" }] }],
    "Stop": [{ "hooks": [{ "type": "command", "command": "python3 ~/.claude/skills/tidy/scripts/hook.py stop" }] }]
  }
}
```

### 其他 AI 工具（Cursor、Codex 等）

把 [`skills/tidy/assets/agents-rules.md`](skills/tidy/assets/agents-rules.md) 粘贴进项目的 `AGENTS.md`。没有 hooks，效果弱一些，可以配合 CI 审计兜底。

## 使用

### 整理一个已经乱了的项目

在 Claude Code 里运行：

```
/tidy
```

（如果和其他插件重名，用全名 `/tidy:tidy`。）

它会：扫描 → 查引用 → 给出整理方案表（**停下来等你确认**）→ 用 `git mv` 执行并修复引用 → 跑构建验证 → 生成 `.claude/tidy.json` 目录约定。之后的会话都会自动遵守这份约定。

也可以直接说「帮我整理一下项目」「看看哪些文件是没用的」。

### 单独使用脚本

```bash
S=skills/tidy/scripts
python3 $S/audit.py <项目>                    # 审计报告（同类问题多时折叠，--all 展开）
python3 $S/audit.py <项目> --changed          # 只看相对 HEAD 新增 / 修改的文件（交付前用）
python3 $S/audit.py <项目> --since 2h         # 只看 2 小时内修改的文件（非 git 项目也能用）
python3 $S/audit.py <项目> --review duplicate-file docs/pack/belt.jpg --reason "课包需要独立图片"   # 记录已核实的告警
python3 $S/audit.py <项目> --fail-on error    # CI 中使用，有 error 时退出码 1
python3 $S/audit.py <项目> --init             # 生成 .claude/tidy.json 草稿
python3 $S/audit.py <项目> --fix-gitignore    # 把应忽略的内容补进 .gitignore（只追加）
python3 $S/refs.py  <项目> src/Root_old.tsx   # 这个文件被谁引用？
```

### 目录约定示例

`.claude/tidy.json`（完整字段见 [config.md](skills/tidy/references/config.md)）：

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

用户明确想要的"例外"（比如学生课包就要中文文件名）按规则加进 `allow`，其他目录仍受检查；成本高、要留在本地但不进 git 的成片、配音、模型登记到 `keepLocal`，审计会要求忽略它们，并且不会建议删除。不想在某个项目启用 hooks，写 `"hooks": false`。

### 审计规则

| 规则 | 级别 | 检查内容 | Hook 拦截 |
|---|---|---|---|
| `artifact-not-ignored` / `tracked-artifact` | error / warn | 依赖、缓存、生成物目录未忽略或已被跟踪 | Stop |
| `secret-tracked` / `secret-not-ignored` | error | `.env`、私钥、凭据文件被跟踪或未忽略（`allow` 不能豁免） | Stop |
| `config-invalid` | error | `.claude/tidy.json` 无法解析 | |
| `keep-local-tracked` / `keep-local-not-ignored` | warn | `keepLocal` 登记的文件被跟踪或未忽略 | Stop |
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

✅ = 新建时由 PreToolUse 直接拦截，Bash 创建的由 Stop 检查兜底。

## 目录结构

```
.
├── .claude-plugin/            # 插件与 marketplace 清单
├── hooks/hooks.json           # 插件 hooks：SessionStart / PreToolUse(Write) / Stop
├── skills/tidy/               # skill 本体，也是 /tidy 命令
│   ├── SKILL.md               # 判断标准、整理流程、删除 vs 归档
│   ├── references/            # 按需读取的细则：目录结构、必要性、命名、文档、配置
│   ├── scripts/
│   │   ├── rules.py           # 共享规则（hooks 和审计用同一套判断）
│   │   ├── audit.py           # 全面审计、--init、--fix-gitignore
│   │   ├── hook.py            # hooks 入口
│   │   └── refs.py            # 引用查找
│   └── assets/                # README 模板、.gitignore 片段、AGENTS.md 规则片段
├── tests/                     # 单元测试（含 hooks 端到端测试）
└── .github/workflows/         # CI：跑测试，并用本插件审计本仓库
```

## 开发

```bash
python3 -m unittest discover -s tests -v
```

## License

MIT
