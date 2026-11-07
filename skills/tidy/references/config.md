# `.tidy.json` 配置说明

项目级配置，放在项目根目录的 `.tidy.json`，所有 Agent 和工具共用这一份。所有字段都可选；没有这个文件时只启用通用规则。旧版位置 `.claude/tidy.json` 仍可读取，审计会提示迁移（`git mv .claude/tidy.json .tidy.json`）。

## 示例：Remotion 视频项目

```json
{
  "layout": {
    "src/": "Remotion 源码：Root.tsx 注册 Composition，compositions/ 每个视频一个文件，components/ 可复用画面组件",
    "public/": "staticFile() 读取的素材：images/、fonts/、audio/（人工录制的配音和背景音乐）",
    "scripts/": "生成配音、批量渲染等 npm scripts 调用的脚本",
    "tools/": "Python 辅助工具，每个子目录自带 README 和依赖",
    "docs/": "视频文案、提示词、分镜等创作资料；过时资料放 docs/archive/"
  },
  "allow": {
    "non-portable-name": ["docs/课程/**"],
    "duplicate-file": ["docs/**/验证记录/**"]
  },
  "keepLocal": {
    "out/**": "成片，渲染约 2 小时，验收后交付",
    "voice/**/*.wav": "已验收配音母带，重配需付费并重新验收"
  },
  "rootAllow": [],
  "disable": [],
  "largeFileMB": 20,
  "maxRootFiles": 15,
  "hooks": true
}
```

## 字段

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `layout` | `{目录: 说明}` | `{}` | 允许的顶层目录及用途。非空时，在未声明的顶层目录下新建文件会被拦截。以 `.` 开头的目录（`.github/`、`.claude/`）和依赖 / 生成物目录不受限制。说明会在每次会话开始时注入给 AI，**写成能指导放置决策的句子**。 |
| `allow` | `{规则 id: glob 列表}` 或 glob 列表 | `{}` | 按规则豁免路径。键为规则 id 时只豁免该规则；键为 `"*"` 时豁免所有规则；直接写列表等同于 `"*"`（旧格式）。**优先按规则写**，例如只给学生课包放开中文名：`{"non-portable-name": ["docs/课程/**"]}`，内部代码仍受检查。密钥规则（`secret-*`）永远不会被 allow 豁免。 |
| `keepLocal` | `{glob: 原因}` 或 glob 列表 | `{}` | **本地保留、不进 git** 的文件：可以重新生成但成本高的交付物和素材（成片、已验收配音、模型权重、课包）。审计要求它们被 `.gitignore` 忽略（`--fix-gitignore` 会自动补），并且不会建议删除；会话开始时会把清单和原因告诉 AI。 |
| `rootAllow` | glob 列表 | `[]` | 额外允许放在根目录的文件（默认白名单见 structure.md）。 |
| `reviewed` | `[{rule, path, reason, sig}]` | `[]` | 已人工核实、确认无需处理的告警。用 `audit.py --review <规则> <路径> --reason <结论>` 添加，不要手写 `sig`（内容指纹）。对象内容变化后告警会带着"请复核"重新出现。密钥类告警不能记录。 |
| `disable` | 规则 id 列表 | `[]` | 整个关闭某些规则。只在全项目都不适用时用；只是部分目录例外请用 `allow` 按规则豁免。 |
| `largeFileMB` | 数字 | `5` | 超过此大小报 `large-file`。 |
| `maxRootFiles` | 数字 | `15` | 根目录文件数上限。 |
| `hooks` | 布尔 | `true` | `false` 时该项目关闭所有自动检查，包括各 Agent 的 hooks 和 git pre-commit（审计脚本仍可用）。 |

glob 写法：相对项目根；匹配文件本身或它的任一上级目录（`docs/a` 会覆盖 `docs/a/` 下所有文件）；`**` 匹配零到多层目录。

配置文件写错（JSON 格式错误、字段类型不对）时，审计报 `config-invalid` 错误，会话开始的提示里也会提醒，其余检查按默认规则进行。

## 规则 id

`config-invalid`、`keep-local-tracked`、`keep-local-not-ignored`、`version-suffix`、`ai-report-doc`、`scratch-file`、`non-portable-name`、`root-stray-file`、`undeclared-dir`、`junk-file`、`secret-file`、`artifact-not-ignored`、`tracked-artifact`、`secret-tracked`、`secret-not-ignored`、`large-file`、`duplicate-file`、`empty-file`、`empty-dir`、`mixed-naming`、`readme-missing-dir`、`layout-missing-dir`、`multiple-lockfiles`、`root-clutter`、`deep-nesting`、`missing-readme`、`missing-gitignore`、`not-git-repo`、`no-layout`。

## 维护

- 新增顶层目录：同时更新 `layout` 和 README「目录结构」。
- 删除顶层目录：从 `layout` 中移除（审计会报 `layout-missing-dir` 提醒）。
- 这个文件应提交进 git，团队和所有 AI 会话共享同一份约定。
