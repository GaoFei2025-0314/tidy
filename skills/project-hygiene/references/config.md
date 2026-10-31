# `.claude/hygiene.json` 配置说明

项目级配置，放在 `.claude/` 下（不占根目录）。所有字段都可选；没有这个文件时只启用通用规则。

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
  "allow": ["public/audio/*.wav"],
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
| `allow` | glob 列表 | `[]` | 豁免路径，所有规则都跳过。例如用户明确要保留的中文文件名 `docs/*.md`。 |
| `rootAllow` | glob 列表 | `[]` | 额外允许放在根目录的文件（默认白名单见 structure.md）。 |
| `disable` | 规则 id 列表 | `[]` | 整个关闭某些规则，例如 `["non-portable-name"]`。 |
| `largeFileMB` | 数字 | `5` | 超过此大小报 `large-file`。 |
| `maxRootFiles` | 数字 | `15` | 根目录文件数上限。 |
| `hooks` | 布尔 | `true` | `false` 时该项目关闭所有 hooks（审计脚本仍可用）。 |

## 规则 id

`version-suffix`、`ai-report-doc`、`scratch-file`、`non-portable-name`、`root-stray-file`、`undeclared-dir`、`junk-file`、`secret-file`、`artifact-not-ignored`、`tracked-artifact`、`secret-tracked`、`secret-not-ignored`、`large-file`、`duplicate-file`、`empty-file`、`empty-dir`、`mixed-naming`、`readme-missing-dir`、`layout-missing-dir`、`multiple-lockfiles`、`root-clutter`、`deep-nesting`、`missing-readme`、`missing-gitignore`、`not-git-repo`、`no-layout`。

## 维护

- 新增顶层目录：同时更新 `layout` 和 README「目录结构」。
- 删除顶层目录：从 `layout` 中移除（审计会报 `layout-missing-dir` 提醒）。
- 这个文件应提交进 git，团队和所有 AI 会话共享同一份约定。
