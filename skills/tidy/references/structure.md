# 目录结构规范

## 总原则

1. **先遵循项目已有约定**，再参考本文。框架有官方约定的（Next.js、Remotion、Django……）以框架为准。
2. **根目录只放"入口级"文件**：别人打开仓库第一眼需要看到的东西。
3. **按职责分目录**：源码、静态资源、脚本工具、文档、测试、生成物，互不混放。
4. **生成物与源文件分离**，生成物一律不进 git。
5. **每个顶层目录都要在 README 里有一句话说明**。
6. 目录层级一般不超过 4–5 层；一个目录只有一个文件时，考虑是否需要这个目录。

## 根目录白名单

根目录只应出现以下类别。其他文件需要有充分理由。

| 类别 | 例子 |
|---|---|
| 说明文档 | `README.md`、`LICENSE`、`CHANGELOG.md`、`CONTRIBUTING.md`、`SECURITY.md` |
| AI 协作规则 | `CLAUDE.md`、`AGENTS.md` |
| 包管理 | `package.json` + **一个** lockfile、`pyproject.toml`、`requirements.txt`、`uv.lock`、`Cargo.toml`、`go.mod` |
| 工具配置 | `tsconfig.json`、`*.config.{js,ts,mjs}`、`.eslintrc*`、`.prettierrc*`、`.editorconfig`、`.nvmrc`、`.python-version` |
| Git / CI | `.gitignore`、`.gitattributes`、`.github/` |
| 环境示例 | `.env.example`（真正的 `.env` 必须被忽略） |
| 容器 | `Dockerfile`、`docker-compose.yml`、`.dockerignore` |
| 任务入口 | `Makefile`、`justfile` |

**不应出现在根目录**：笔记和提示词（→ `docs/`）、一次性脚本（→ `scripts/` 或删除）、素材文件（→ `public/` / `assets/`）、渲染输出（→ 忽略的 `out/`）、AI 任务报告（→ 删除，内容进 commit message）。

## 通用目录含义

| 目录 | 放什么 | 进 git？ |
|---|---|---|
| `src/` | 应用 / 库源码 | ✅ |
| `public/` | 原样提供的静态资源（框架约定时使用） | ✅（大文件除外） |
| `assets/` | 源素材（无框架约定时使用，与 `public/` 二选一） | ✅（大文件除外） |
| `scripts/` | 开发 / 构建 / 运维脚本，可被 `package.json` scripts 或 Makefile 调用 | ✅ |
| `tools/` | 独立的辅助工具（自带依赖的子项目）。**与 `scripts/` 二选一**，除非两者职责确实不同并在 README 中说明 | ✅ |
| `tests/` 或就近 `*.test.ts` | 测试，按语言惯例 | ✅ |
| `docs/` | 长期有效的文档 | ✅ |
| `docs/archive/` | 不可再生但已过时的资料 | ✅ |
| `build/` `dist/` `out/` | 构建 / 渲染输出 | ❌ 忽略 |
| `node_modules/` `.venv/` | 依赖 | ❌ 忽略 |
| `.scratch/` | 临时实验区（可选） | ❌ 忽略 |

> `build/` 在部分项目中是**源码**（例如构建配置脚本目录）。判断前先看 `.gitignore` 和其内容。

## 常见项目布局

### Node / TypeScript Web 应用

```
.
├── src/
│   ├── components/
│   ├── lib/            # 与框架无关的工具函数
│   └── index.ts
├── public/
├── tests/              # 或与源码就近放 *.test.ts
├── scripts/
├── docs/
├── package.json
├── package-lock.json   # 只保留一种包管理器的 lockfile
├── tsconfig.json
└── README.md
```

### Remotion 视频项目

```
.
├── src/
│   ├── Root.tsx               # 注册 Composition
│   ├── index.ts               # registerRoot 入口
│   ├── compositions/          # 每个视频一个文件或子目录
│   ├── components/            # 可复用的画面组件
│   └── lib/                   # 时间轴计算、字幕解析等
├── public/                    # staticFile() 读取的素材：图片、字体、背景音乐、配音
│   └── audio/
├── scripts/                   # 生成配音、批量渲染等脚本
├── docs/                      # 提示词、分镜、脚本文案
├── out/                       # 渲染结果（忽略）
├── remotion.config.ts
└── package.json
```

要点：
- 渲染输出 `out/`、打包产物 `build/` 一律忽略。
- 配音等**生成的**音频：如果能用脚本重新生成，就忽略它，并在 README 写生成命令；如果是人工录制的原始素材，放 `public/audio/`，体积大时考虑 Git LFS。
- 视频文案、提示词属于文档，放 `docs/`，不要散落在根目录。

### Python 项目

```
.
├── src/<package_name>/       # 或扁平布局 <package_name>/
│   ├── __init__.py
│   └── ...
├── tests/
├── scripts/
├── docs/
├── pyproject.toml
└── README.md
```

小型脚本项目可以不用 `src/`，但入口脚本最多一两个，其余放进包或 `scripts/`。

### 混合项目（例：Node 主项目 + Python 辅助工具）

一个仓库里有两套语言工具链时，**让副工具链自成一个子目录**，不要把两套依赖都堆在根目录：

```
.
├── src/                    # Node 主项目
├── public/
├── tools/
│   └── tts/                # Python 工具，自带依赖
│       ├── README.md       # 用途、安装、运行方式
│       ├── pyproject.toml  # 或 requirements.txt
│       ├── .venv/          # 忽略
│       └── generate.py
├── package.json
└── README.md               # 在「目录结构」里说明 tools/tts 的用途
```

如果 `.venv/` 必须放在根目录（例如工具链要求），至少保证它被忽略，并在 README 说明是给哪个工具用的。

### Monorepo

```
.
├── apps/        # 可部署的应用
├── packages/    # 共享库
├── tools/       # 仓库级工具
└── docs/
```

## 素材放哪

| 素材 | 位置 |
|---|---|
| 运行时需要、框架原样提供 | `public/`（按类型分子目录：`images/`、`audio/`、`fonts/`） |
| 被代码 import、会被打包处理 | `src/assets/` |
| 原始素材（PSD、录音原文件），不被代码使用 | 不进仓库，或 Git LFS，README 写明存放位置 |
| 可由脚本生成 | 忽略，README 写生成命令 |
