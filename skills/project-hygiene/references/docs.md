# 文档与归档规范

## README 最低要求

每个项目的 README 至少回答：

1. **这是什么**：一两句话说明项目用途。
2. **怎么跑起来**：环境要求、安装、启动命令（可复制粘贴）。
3. **常用命令**：开发、构建、测试、渲染等。
4. **目录结构**：每个顶层目录一句话。新增顶层目录时必须更新这里。
5. **配置**：需要哪些环境变量（只写变量名和用途，值放 `.env.example`）。

模板见 [../assets/README.template.md](../assets/README.template.md)。

README 不是变更日志，不要写"今天修复了 xxx"。

## docs/ 目录布局

```
docs/
├── README.md             # docs 索引（文档较多时）
├── architecture.md       # 架构说明
├── prompts.md            # 提示词、文案等创作资料
├── decisions/            # 架构决策记录（ADR），可选
│   └── 0001-use-remotion.md
└── archive/              # 已过时但有参考价值的资料
    ├── README.md
    └── 2026-09-old-voice-pipeline.md
```

- 文档少（≤3 篇）时，不必建 `docs/README.md` 索引。
- 子项目（如 `tools/tts/`）的文档放在子项目自己的 `README.md` 里。

## 什么内容写进文档，什么不写

| 内容 | 去处 |
|---|---|
| 本次改了什么、怎么改的 | commit message / PR 描述 |
| 任务完成总结、进度汇报 | 回复给用户，**不落盘** |
| 如何运行、目录说明 | README |
| 为什么选这个方案（长期有效） | `docs/decisions/` |
| 用户的提示词、文案、调研 | `docs/` |
| 对外发布的变更 | `CHANGELOG.md`（项目需要时） |

## 归档规则

**git 历史本身就是代码的归档**——过时代码直接删除，不需要 `old/`、`archive/` 目录存放旧代码。

`docs/archive/` 只用于**不可再生的非代码资料**：旧版提示词、调研笔记、废弃方案的设计文档、历史会议记录。

归档时：

1. 文件名加日期前缀：`YYYY-MM-<主题>.md`，例如 `2026-09-old-voice-pipeline.md`。
2. 在 `docs/archive/README.md` 追加一行：

   ```markdown
   | 文件 | 归档日期 | 原因 |
   |---|---|---|
   | 2026-09-old-voice-pipeline.md | 2026-10-16 | 改用 ElevenLabs，旧 Azure TTS 流程停用 |
   ```

3. 文件开头加一行说明：`> 已归档（2026-10-16）：<原因>。当前做法见 <链接>。`

大体积素材（音视频、数据集）不归档进 git：移到网盘 / 对象存储，在 README 记录位置。

## AI 协作规则文件

`CLAUDE.md` / `AGENTS.md` 写给 AI 看：项目约定、常用命令、禁止事项。保持简短（一屏内），只写 AI 从代码中读不出来的东西。整洁规范可直接使用 [../assets/agents-rules.md](../assets/agents-rules.md)。
