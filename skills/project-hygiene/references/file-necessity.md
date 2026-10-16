# 文件必要性判定

## 判定一个文件"在用"

满足任意一条即视为在用，**不要删除**：

- 被源码 import / require / 动态加载（含字符串路径，如 `staticFile("audio/intro.mp3")`、`open("data/x.csv")`）；
- 被配置引用：`package.json` 的 `main` / `bin` / `scripts` / `files`，`tsconfig.json` 的 `include`，`pyproject.toml` 入口，CI 工作流，Dockerfile；
- 被框架按约定加载（Next.js `app/`、`pages/`，Remotion 的 `src/index.ts`，`conftest.py`，`__init__.py`）；
- 被文档引用且文档仍有效；
- 是工具链的配置文件，且该工具在依赖中。

## 验证无引用的方法

```bash
# 按文件名（不含扩展名）搜索引用，排除依赖和产物目录
name=foo-bar
grep -rn --exclude-dir={node_modules,.git,.venv,build,dist,out} -e "$name" .

# JS/TS 可用工具检测未使用文件和依赖
npx knip            # 未使用的文件、导出、依赖
npx depcheck        # 未使用的依赖

# Python
pip install vulture && vulture src/        # 未使用代码
pip install deptry && deptry .              # 未使用 / 缺失的依赖
```

注意动态引用：模板字符串拼路径（`` `audio/${id}.mp3` ``）、glob 加载、反射。搜不到引用 ≠ 一定没用，此时标为「待确认」。

## 按类别判断

| 类别 | 例子 | 判断 |
|---|---|---|
| 生成物 | `build/`、`dist/`、`out/`、`*.pyc`、渲染出的 mp4 | 删除 + 忽略 |
| 依赖 | `node_modules/`、`.venv/` | 忽略（本地保留） |
| 缓存 / 日志 | `.cache/`、`__pycache__/`、`*.log`、`.DS_Store` | 删除 + 忽略 |
| 版本副本 | `x_v2.ts`、`x_old.py`、`x.bak`、`x copy.md`、`final_final.mp4` | 确认哪个是当前版本，合并后删除其余 |
| AI 任务报告 | `IMPLEMENTATION_SUMMARY.md`、`FIX_REPORT.md`、`PROGRESS.md` | 有价值的内容合并进 README / docs，然后删除 |
| 临时脚本 | `test.py`、`debug.js`、`tmp.ts`、`check_*.py`（不在测试体系内） | 删除；有复用价值则改名放进 `scripts/` 并写用途注释 |
| 脚手架样板 | 未引用的 `logo.svg`、示例组件、`App.test.js` 默认测试 | 确认无引用后删除 |
| 空文件 / 空目录 | 0 字节文件、只有 `.gitkeep` 的占位目录 | 删除，除非有约定意义（`__init__.py`、`py.typed`、明确需要的 `.gitkeep`） |
| 重复文件 | 内容完全相同的两个文件 | 保留一份，修正引用 |
| 重复配置 | 同一工具有两份配置 | 保留一处 |
| 多个 lockfile | `package-lock.json` + `yarn.lock` + `pnpm-lock.yaml` | 只保留实际在用的包管理器的那个 |
| 密钥 | `.env`、`*.pem`、`credentials.json` | 必须忽略；已提交则需轮换密钥并清理历史 |
| 用户原始素材 | 录音、图片、提示词、数据 | **不可再生，不能擅自删除**，移到正确位置或归档 |

## 依赖的必要性

- `package.json` / `requirements.txt` 里的每个依赖都应能在代码或配置中找到使用处。
- 开发依赖放 `devDependencies` / 可选依赖组，不要混入运行时依赖。
- 删除功能时，同步删除只为它引入的依赖。
