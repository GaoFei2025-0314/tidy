## 文件整洁规范

<!-- 给不支持 Claude Code hooks 的 AI 工具（Cursor、Codex 等）使用；Claude Code 安装插件后会自动注入同等规则。 -->

新建文件前先问：必要吗（能否并入已有文件）？放哪（遵循现有目录约定）？叫什么（与同目录风格一致、只用 ASCII）？该提交吗（生成物 / 依赖 / 密钥 / 大文件不提交）？

禁止：
- 在根目录创建临时 / 调试脚本（`test.py`、`debug.js` 等）。临时文件放 `.scratch/`（已忽略）或系统临时目录，任务结束即删。
- 复制出 `*_v2`、`*_new`、`*_old`、`*.bak`、`* copy` 等副本。直接改原文件，历史交给 git。
- 生成任务总结类文档（`*_SUMMARY.md`、`*_REPORT.md`、`PROGRESS.md`）。总结写进回复和 commit message。
- 提交 `build/`、`dist/`、`out/`、`node_modules/`、`.venv/`、日志、渲染输出、`.env`。
- 使用中文、空格、括号作为文件名。
- 保留注释掉的旧代码、未使用的依赖、未引用的脚手架样板。

每次任务结束前：检查 `git status` 中新增的文件是否都必要；删除临时文件；新增顶层目录时更新 README「目录结构」；新出现的生成物补进 `.gitignore`。

删除或批量移动文件前先征得同意；移动文件用 `git mv`，并修复所有引用。

目录约定见 `.claude/hygiene.json` 的 `layout`：新文件放进已声明的目录，确需新顶层目录时先在 layout 和 README 中登记。
