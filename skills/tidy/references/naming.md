# 命名规范

## 总原则

1. **一致性优先于个人偏好**：先看同目录已有文件用什么风格，跟着用。
2. **名字说明用途**，不说明状态或历史：`subtitle-parser.ts` ✅，`new-parser.ts` ❌，`parser-fixed.ts` ❌。
3. **路径只用 ASCII**：小写字母、数字、`-`、`_`、`.`。不用中文、空格、括号、`&`、`#`。中文写在文件内容的标题里。
4. 日期一律 ISO 格式并放在前面，便于排序：`2026-10-16-meeting.md`。

## 各语言约定

| 场景 | 风格 | 例子 |
|---|---|---|
| 目录 | kebab-case 小写 | `voice-tools/`、`compositions/` |
| JS/TS 普通模块 | kebab-case（或项目既有的 camelCase） | `format-time.ts` |
| React / Vue 组件 | PascalCase | `TitleCard.tsx` |
| React hooks | camelCase，以 `use` 开头 | `useAudioDuration.ts` |
| Python 模块 / 包 | snake_case | `generate_voice.py` |
| Shell 脚本 | kebab-case | `render-all.sh` |
| Markdown 文档 | kebab-case；约定俗成的大写文件保持大写 | `prompt-guide.md`、`README.md`、`CHANGELOG.md` |
| 素材 | kebab-case，带语义 | `intro-bgm.mp3`、`logo-dark.svg` |
| 环境变量 | UPPER_SNAKE_CASE | `ELEVENLABS_API_KEY` |

同一目录、同一扩展名下，**不要 kebab-case 和 snake_case 混用**。

## 禁止的命名模式

| ❌ 模式 | 问题 | ✅ 改为 |
|---|---|---|
| `foo_v2.ts`、`foo-new.ts`、`foo_old.py` | 版本应由 git 管理 | `foo.ts` |
| `foo.bak`、`foo.backup.ts`、`foo.orig` | 备份应由 git 管理 | 删除 |
| `foo copy.md`、`foo (1).png`、`foo副本.md` | 系统复制产生的副本 | 删除或重命名为有意义的名字 |
| `final.mp4`、`final_final.mp4`、`最终版.md` | 状态词没有信息量 | 按内容命名：`launch-trailer.mp4` |
| `test.py`、`tmp.js`、`untitled.md`、`aaa.txt` | 看不出用途 | 按用途命名，或删除 |
| `utils2.ts`、`helpers-new.ts` | 应合并 | 合并进 `utils.ts` 或按职责拆分 |
| `提示词分享.md` | 非 ASCII 路径在终端、URL、CI 中易出问题 | `docs/prompts.md`，文件内写 `# 提示词分享` |
| `My Document.docx` | 空格需要转义 | `my-document.docx` |

## 重命名时

- 用 `git mv old new` 保留历史。
- 重命名后 grep 旧名称，修复所有引用。
- macOS 文件系统默认大小写不敏感，只改大小写时用两步：`git mv Foo.ts foo.tmp && git mv foo.tmp foo.ts`。
