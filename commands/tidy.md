---
description: 审计并整理当前项目的文件结构（先出方案，确认后才执行）
argument-hint: "[子目录，默认整个项目]"
---

使用 project-hygiene skill，按 SKILL.md「模式二：整理已有项目」整理 `$ARGUMENTS`（为空则整理整个项目）：

1. 运行 audit.py 扫描；读 README、包配置和入口文件理解项目。
2. 对每个疑似无用 / 要移动的文件运行 refs.py 查引用。
3. 输出整理方案表（路径 / 动作 / 目标位置 / 理由），不确定的标「待确认」。**到这里停下，等我确认。**
4. 我确认后：git mv 执行、修复引用、跑构建或测试验证、更新 README「目录结构」、补 .gitignore。
5. 最后生成或更新 .claude/hygiene.json 的 layout，让以后的会话自动遵守。
