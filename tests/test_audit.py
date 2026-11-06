import contextlib
import io
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/tidy/scripts"
sys.path.insert(0, str(SCRIPTS))
import audit  # noqa: E402
import refs  # noqa: E402
import rules  # noqa: E402


def write(root: Path, rel: str, content: str = "x" * 100) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def git_commit_all(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
        cwd=root, check=True,
    )


def rules_for(findings, path):
    return {f.rule for f in findings if f.path == path}


LAYOUT = {"layout": {"src/": "源码", "docs/": "文档"}}


class CheckPathTest(unittest.TestCase):
    def setUp(self):
        self.cfg = rules.Config(layout={"src/": "源码", "docs/": "文档", "tests/": "测试"}, exists=True)

    def rules(self, rel, cfg=None):
        return {f.rule for f in rules.check_path(rel, cfg or self.cfg)}

    def test_good_paths(self):
        for rel in ["src/compositions/Intro.tsx", "src/lib/format-time.ts", "README.md", "package.json",
                    "docs/implementation-notes.md", "docs/2026-10-summary.md", "remotion.config.ts",
                    ".github/workflows/ci.yml", "tests/test_utils.py"]:
            self.assertEqual(self.rules(rel), set(), rel)

    def test_bad_paths(self):
        self.assertIn("version-suffix", self.rules("src/Title_v2.tsx"))
        self.assertIn("version-suffix", self.rules("src/Title.backup.tsx"))
        self.assertIn("ai-report-doc", self.rules("FIX_REPORT.md"))
        self.assertIn("scratch-file", self.rules("debug.py"))
        self.assertIn("non-portable-name", self.rules("docs/提示词.md"))
        self.assertIn("root-stray-file", self.rules("notes.md"))
        self.assertIn("undeclared-dir", self.rules("newdir/x.ts"))
        self.assertIn("secret-file", self.rules("src/.env.local"))

    def test_config_allow_and_disable(self):
        cfg = rules.Config(allow=["docs/*.md"], disable=["root-stray-file"])
        self.assertEqual(self.rules("docs/提示词.md", cfg), set())
        self.assertEqual(self.rules("notes.md", cfg), set())
        cfg = rules.Config(root_allow=["notes.md"])
        self.assertEqual(self.rules("notes.md", cfg), set())

    def test_no_layout_means_no_undeclared_dir(self):
        self.assertEqual(self.rules("newdir/x.ts", rules.Config()), set())


class CleanProjectTest(unittest.TestCase):
    def test_clean_project_has_no_findings(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            write(root, "README.md", "# demo\n\n- src/ 源码\n- docs/ 文档\n")
            write(root, ".gitignore", "node_modules/\nout/\n.env\n")
            write(root, ".claude/tidy.json", json.dumps(LAYOUT))
            write(root, "package.json", '{"name": "demo"}')
            write(root, "src/index.ts", "export const a = 1\n")
            write(root, "docs/prompts.md", "# 提示词\n")
            write(root, "node_modules/x/index.js")
            write(root, "out/video.mp4")
            write(root, ".env", "KEY=1")
            git_commit_all(root)
            findings, summary = audit.audit(root)
            self.assertEqual(findings, [], [f"{f.rule} {f.path}" for f in findings])
            self.assertTrue(summary["git"])
            self.assertTrue(summary["config"])


class MessyProjectTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        root = cls.root = Path(cls._tmp.name)
        write(root, "README.md", "# demo\n- src/\n")
        write(root, ".gitignore", "node_modules/\n")
        write(root, "package.json", "{}")
        write(root, "package-lock.json", "{}")
        write(root, "yarn.lock", "")
        write(root, "提示词分享.md")
        write(root, "IMPLEMENTATION_SUMMARY.md")
        write(root, "test.py", "print(1)")
        write(root, ".env", "KEY=1")
        write(root, ".venv/bin/python")
        write(root, "out/video.mp4")
        write(root, "src/Root.tsx", "a" * 200)
        write(root, "src/Root_old.tsx", "a" * 200)
        write(root, "src/empty.ts", "")
        write(root, "tools/gen_voice.py")
        write(root, "tools/merge_audio.py", "y" * 100)
        write(root, "tools/split-audio.py", "z" * 100)
        write(root, "voice/intro (1).mp3", "w" * 100)
        git_commit_all(root)
        cls.findings, cls.summary = audit.audit(root)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_dependency_dir_not_ignored_is_error(self):
        f = [x for x in self.findings if x.path == ".venv/"]
        self.assertEqual(f[0].severity, "error")

    def test_tracked_output_dir(self):
        self.assertIn("tracked-artifact", rules_for(self.findings, "out/"))

    def test_secret_tracked(self):
        self.assertIn("secret-tracked", rules_for(self.findings, ".env"))

    def test_naming_and_placement(self):
        self.assertIn("non-portable-name", rules_for(self.findings, "提示词分享.md"))
        self.assertIn("root-stray-file", rules_for(self.findings, "提示词分享.md"))
        self.assertIn("version-suffix", rules_for(self.findings, "src/Root_old.tsx"))
        self.assertIn("version-suffix", rules_for(self.findings, "voice/intro (1).mp3"))

    def test_ai_habits(self):
        self.assertIn("ai-report-doc", rules_for(self.findings, "IMPLEMENTATION_SUMMARY.md"))
        self.assertNotIn("root-stray-file", rules_for(self.findings, "IMPLEMENTATION_SUMMARY.md"))
        self.assertIn("scratch-file", rules_for(self.findings, "test.py"))

    def test_misc(self):
        found = {f.rule for f in self.findings}
        self.assertTrue({"multiple-lockfiles", "empty-file", "duplicate-file", "mixed-naming",
                         "readme-missing-dir", "no-layout"} <= found)

    def test_fail_on_exit_code(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(audit.main([str(self.root), "--fail-on", "error", "--format", "json"]), 1)


class InitAndFixTest(unittest.TestCase):
    def test_init_and_fix_gitignore(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            write(root, "README.md", "# demo\n")
            write(root, "src/a.ts")
            write(root, "voice/a.mp3")
            write(root, "node_modules/x.js")
            write(root, "dist/a.js")
            write(root, "run.log")
            write(root, ".env", "K=1")
            git_commit_all(root)
            subprocess.run(["git", "rm", "-rq", "--cached", "node_modules", "dist", "run.log", ".env"],
                           cwd=root, check=True)

            quiet = contextlib.redirect_stdout(io.StringIO())
            quiet.__enter__()
            self.addCleanup(quiet.__exit__, None, None, None)
            self.assertEqual(audit.main([str(root), "--init"]), 0)
            cfg = json.loads((root / ".claude/tidy.json").read_text(encoding="utf-8"))
            self.assertEqual(set(cfg["layout"]), {"src/", "voice/"})
            self.assertEqual(audit.main([str(root), "--init"]), 1)  # 不覆盖

            audit.main([str(root), "--fix-gitignore"])
            gi = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
            for entry in ["node_modules/", "dist/", "*.log", ".env*", "!.env.example"]:
                self.assertIn(entry, gi)
            findings, _ = audit.audit(root)
            self.assertFalse({"artifact-not-ignored", "secret-not-ignored", "junk-file"} & {f.rule for f in findings})


class RefsTest(unittest.TestCase):
    def test_refs(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            write(root, "src/index.ts", 'import {A} from "./Title";\nconst v = staticFile("audio/intro.mp3");\n')
            write(root, "src/Title.tsx")
            write(root, "src/Title_old.tsx")
            write(root, "public/audio/intro.mp3")
            res = refs.find_refs(root, ["src/Title.tsx", "src/Title_old.tsx", "public/audio/intro.mp3", "src/index.ts"])
            self.assertEqual(res["src/Title.tsx"]["verdict"], "in-use")
            self.assertEqual(res["src/Title_old.tsx"]["verdict"], "unreferenced")
            self.assertEqual(res["public/audio/intro.mp3"]["verdict"], "in-use")
            self.assertEqual(res["src/index.ts"]["verdict"], "convention")


class HookTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        write(self.root, "README.md", "# demo\n- src/\n- docs/\n")
        write(self.root, ".gitignore", "node_modules/\n.scratch/\n")
        write(self.root, ".claude/tidy.json", json.dumps(LAYOUT))
        write(self.root, "src/index.ts")
        write(self.root, "legacy_old.py")  # 会话前就存在的问题不应被 hook 追究
        git_commit_all(self.root)
        self.session = "t1"

    def tearDown(self):
        self._tmp.cleanup()

    def hook(self, event, **extra):
        data = {"session_id": self.session, "cwd": str(self.root), **extra}
        r = subprocess.run([sys.executable, str(SCRIPTS / "hook.py"), event], input=json.dumps(data),
                           capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})
        return r.returncode, r.stdout, r.stderr

    def write_hook(self, rel):
        return self.hook("pre-write", tool_name="Write", tool_input={"file_path": str(self.root / rel)})

    def test_session_start_injects_layout(self):
        code, out, _ = self.hook("session-start")
        self.assertEqual(code, 0)
        self.assertIn("src/ — 源码", out)

    def test_pre_write(self):
        self.assertEqual(self.write_hook("src/Title_v2.tsx")[0], 2)
        self.assertEqual(self.write_hook("FIX_REPORT.md")[0], 2)
        self.assertEqual(self.write_hook("newdir/a.ts")[0], 2)
        self.assertEqual(self.write_hook("src/compositions/Intro.tsx")[0], 0)
        self.assertEqual(self.write_hook(".scratch/try.py")[0], 0)
        self.assertEqual(self.write_hook("legacy_old.py")[0], 0)  # 已存在的文件不拦
        self.assertEqual(self.hook("pre-write", tool_input={"file_path": "/tmp/elsewhere/x_v2.py"})[0], 0)

    def test_stop_flags_only_new_files_once(self):
        self.hook("session-start")
        self.assertEqual(self.hook("stop", stop_hook_active=False)[0], 0)
        write(self.root, "check_output.py")
        write(self.root, "src/lib/format-time.ts")
        code, _, err = self.hook("stop", stop_hook_active=False)
        self.assertEqual(code, 2)
        self.assertIn("check_output.py", err)
        self.assertNotIn("format-time", err)
        self.assertNotIn("legacy_old.py", err)
        self.assertEqual(self.hook("stop", stop_hook_active=True)[0], 0)
        self.assertEqual(self.hook("stop", stop_hook_active=False)[0], 0)  # 已接受，不再重复提醒

    def test_pre_write_checks_nested_output_name(self):
        self.assertEqual(self.write_hook("docs/coverage/notes_v2.md")[0], 2)

    def test_session_start_reports_bad_config_and_keep_local(self):
        write(self.root, ".claude/tidy.json", "{bad")
        self.assertIn("无法解析", self.hook("session-start")[1])
        write(self.root, ".claude/tidy.json", json.dumps({**LAYOUT, "keepLocal": {"out/**": "成片"}}))
        self.assertIn("out/** — 成片", self.hook("session-start")[1])

    def test_stop_flags_keep_local_not_ignored(self):
        write(self.root, ".claude/tidy.json", json.dumps({**LAYOUT, "keepLocal": ["src/media/*.wav"]}))
        self.hook("session-start")
        write(self.root, "src/media/a.wav")
        code, _, err = self.hook("stop", stop_hook_active=False)
        self.assertEqual(code, 2)
        self.assertIn("keepLocal", err)

    def test_stop_catches_files_after_git_add_and_commit(self):
        self.hook("session-start")
        write(self.root, "debug.py")
        subprocess.run(["git", "add", "debug.py"], cwd=self.root, check=True)
        code, _, err = self.hook("stop", stop_hook_active=False)
        self.assertEqual(code, 2)
        self.assertIn("debug.py", err)
        self.hook("stop", stop_hook_active=True)  # 接受
        write(self.root, "src/notes_old.md")
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"],
                       cwd=self.root, check=True)
        code, _, err = self.hook("stop", stop_hook_active=False)
        self.assertEqual(code, 2)
        self.assertIn("notes_old.md", err)
        self.assertNotIn("debug.py", err)

    def test_stop_accepts_legacy_state_file(self):
        from hook import state_file  # noqa: E402
        sf = state_file(self.root.resolve(), self.session)
        sf.write_text("[]", encoding="utf-8")
        self.assertEqual(self.hook("stop", stop_hook_active=False)[0], 0)  # 旧格式：重建基线，不误报

    def test_hooks_can_be_disabled(self):
        write(self.root, ".claude/tidy.json", json.dumps({"hooks": False}))
        self.assertEqual(self.write_hook("FIX_REPORT.md")[0], 0)


class NonGitTest(unittest.TestCase):
    def test_gitignore_parsed_without_git(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            write(root, "README.md", "# demo\n")
            write(root, ".gitignore", "node_modules/\n/out/\n*.log\n")
            write(root, "node_modules/a.js")
            write(root, "out/a.mp4")
            write(root, "logs/run.log")
            findings, summary = audit.audit(root)
            self.assertFalse(summary["git"])
            self.assertIn(("not-git-repo", "."), {(f.rule, f.path) for f in findings})
            self.assertFalse(any(f.path.startswith(("node_modules", "out", "logs/run.log")) for f in findings))



class RegressionTest(unittest.TestCase):
    """真实项目（课程视频）里暴露出的误报和漏洞。"""

    def rules(self, rel, cfg=None):
        return {f.rule for f in rules.check_path(rel, cfg or rules.Config())}

    def test_allow_never_exempts_secrets(self):
        cfg = rules.Config(allow={"*": ["config/**"], "secret-file": ["config/**"]})
        self.assertIn("secret-file", self.rules("config/.env", cfg))
        self.assertEqual(self.rules("config/notes_v2.md", cfg), set())

    def test_copy_means_copywriting(self):
        for rel in ["src/additional-copy.ts", "docs/hero_copy.md"]:
            self.assertNotIn("version-suffix", self.rules(rel), rel)
        for rel in ["docs/intro copy.md", "docs/intro copy 2.md", "src/Title_copy2.tsx"]:
            self.assertIn("version-suffix", self.rules(rel), rel)

    def test_scratch_prefix_only_at_root(self):
        self.assertIn("scratch-file", self.rules("check_render.py"))
        self.assertNotIn("scratch-file", self.rules("tools/check_language.py"))
        self.assertIn("scratch-file", self.rules("tools/debug.py"))

    def test_per_rule_allow(self):
        cfg = rules.Config(allow={"non-portable-name": ["docs/课程/**"]})
        self.assertEqual(self.rules("docs/课程/L01/讲义.md", cfg), set())
        self.assertIn("non-portable-name", self.rules("tools/生成.py", cfg))
        self.assertIn("version-suffix", self.rules("docs/课程/讲义_v2.md", cfg))
        self.assertEqual(self.rules("docs/a/b_old.md", rules.Config(allow=["docs/a"])), set())  # 旧格式

    def test_nested_output_dir_name_is_content(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            write(root, "README.md", "# demo\n- docs/\n- packages/\n")
            write(root, ".gitignore", "node_modules/\n")
            write(root, "docs/L12/coverage/report.md")
            write(root, "packages/web/package.json", "{}")
            write(root, "packages/web/dist/a.js")
            git_commit_all(root)
            self.assertIsNone(rules.artifact_dir_of("docs/L12/coverage/report.md", root))
            self.assertEqual(rules.artifact_dir_of("packages/web/dist/a.js", root), "packages/web/dist/")
            findings, _ = audit.audit(root)
            self.assertFalse(any(f.path.startswith("docs/L12") and f.rule.endswith("artifact") for f in findings))
            self.assertIn("tracked-artifact", rules_for(findings, "packages/web/dist/"))

    def test_invalid_config_is_reported(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            write(root, ".claude/tidy.json", '{"layout": {"src/": "x"},}')
            cfg = rules.load_config(root)
            self.assertTrue(cfg.error)
            findings, _ = audit.audit(root)
            self.assertIn("config-invalid", {f.rule for f in findings})
            write(root, ".claude/tidy.json", '{"allow": "docs/*"}')
            self.assertTrue(rules.load_config(root).error)

    def test_refs_skips_secret_files(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            write(root, "src/intro.ts")
            write(root, ".env", "INTRO_TOKEN=intro.ts-secret-value")
            res = refs.find_refs(root, ["src/intro.ts"])
            self.assertEqual(res["src/intro.ts"]["verdict"], "unreferenced")
            self.assertNotIn("secret-value", json.dumps(res))

    def test_empty_dir_vs_local_only(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            write(root, "README.md", "# demo\n- docs/\n")
            write(root, ".gitignore", "*.png\n")
            write(root, "docs/L01/figures/a.png")
            (root / "docs/L02/figures").mkdir(parents=True)
            write(root, "docs/L01/notes.md")
            git_commit_all(root)
            findings, _ = audit.audit(root)
            empty = {f.path for f in findings if f.rule == "empty-dir"}
            self.assertEqual(empty, {"docs/L02/figures/"})

    def test_duplicates_grouped_and_exemptible(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            write(root, "README.md", "# demo\n- frames/\n- src/\n")
            write(root, ".gitignore", "x\n")
            for i in range(4):
                write(root, f"frames/{i}a.jpg", str(i) * 100)
                write(root, f"frames/{i}b.jpg", str(i) * 100)
            write(root, "src/a.txt", "q" * 100)
            write(root, "src/b.txt", "q" * 100)
            git_commit_all(root)
            dup = [f for f in audit.audit(root)[0] if f.rule == "duplicate-file"]
            self.assertEqual(len(dup), 2)
            self.assertIn("frames/", {f.path for f in dup})
            cfg = rules.Config(allow={"duplicate-file": ["frames/**"]})
            dup = [f for f in audit.audit(root, cfg)[0] if f.rule == "duplicate-file"]
            self.assertEqual([f.path for f in dup], ["src/a.txt"])

    def test_text_report_folds_long_rules(self):
        fs = [rules.Finding("empty-dir", "info", f"d{i}/", "空目录", "删") for i in range(20)]
        summary = {"root": ".", "git": True, "config": True, "scanned_files": 0, "scanned_dirs": 0,
                   "skipped_dirs": 0, "counts": {"error": 0, "warn": 0, "info": 20}}
        text = audit.render_text(fs, summary)
        self.assertIn("另有 15 条", text)
        self.assertNotIn("d19/", text)
        self.assertIn("d19/", audit.render_text(fs, summary, show_all=True))

    def test_keep_local(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            write(root, "README.md", "# demo\n- voice/\n")
            write(root, ".gitignore", "node_modules/\n")
            write(root, ".claude/tidy.json", json.dumps(
                {"layout": {"voice/": "配音"}, "keepLocal": {"voice/**/*.wav": "已验收配音母带，重配成本高"}}))
            write(root, "voice/L01/a.wav")
            write(root, "voice/L01/b.wav")
            write(root, "voice/L01/script.md")
            git_commit_all(root)
            subprocess.run(["git", "rm", "-q", "--cached", "voice/L01/b.wav"], cwd=root, check=True)
            findings, _ = audit.audit(root)
            self.assertIn("keep-local-tracked", rules_for(findings, "voice/L01/a.wav"))
            self.assertIn("keep-local-not-ignored", rules_for(findings, "voice/L01/b.wav"))
            with contextlib.redirect_stdout(io.StringIO()):
                audit.main([str(root), "--fix-gitignore"])
            self.assertIn("voice/**/*.wav", (root / ".gitignore").read_text(encoding="utf-8"))
            findings, _ = audit.audit(root)
            self.assertNotIn("keep-local-not-ignored", {f.rule for f in findings})
            self.assertTrue((root / "voice/L01/b.wav").exists())


class WorkflowTest(unittest.TestCase):
    """日常使用：只看本次变化、记录已核实的告警、交付副本。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = root = Path(self._tmp.name)
        write(root, "README.md", "# demo\n- src/\n- docs/\n")
        write(root, ".gitignore", "node_modules/\n")
        write(root, ".claude/tidy.json", json.dumps(LAYOUT))
        write(root, "src/old_v2.ts")
        write(root, "src/plates/belt.jpg", "j" * 200)
        write(root, "docs/pack/belt.jpg", "j" * 200)
        git_commit_all(root)

    def tearDown(self):
        self._tmp.cleanup()

    def run_json(self, *args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = audit.main([str(self.root), "--format", "json", *args])
        return code, json.loads(buf.getvalue())

    def test_changed_only_reports_new_problems(self):
        write(self.root, "src/new_v2.ts")
        _, data = self.run_json("--changed")
        paths = {f["path"] for f in data["findings"]}
        self.assertIn("src/new_v2.ts", paths)
        self.assertNotIn("src/old_v2.ts", paths)
        _, full = self.run_json()
        self.assertIn("src/old_v2.ts", {f["path"] for f in full["findings"]})

    def test_since_uses_mtime(self):
        import os
        old = time.time() - 3 * 86400
        for p in self.root.rglob("*"):
            if p.is_file() and ".git" not in p.parts:
                os.utime(p, (old, old))
        write(self.root, "src/fresh_v2.ts")
        _, data = self.run_json("--since", "1h")
        self.assertEqual({f["path"] for f in data["findings"]}, {"src/fresh_v2.ts"})

    def test_cross_dir_duplicate_labelled_as_delivery_copy(self):
        dup = [f for f in audit.audit(self.root)[0] if f.rule == "duplicate-file"]
        self.assertEqual(len(dup), 1)
        self.assertIn("交付副本", dup[0].message)

    def test_review_lifecycle(self):
        quiet = contextlib.redirect_stderr(io.StringIO())
        with quiet, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(audit.main([str(self.root), "--review", "version-suffix", "src/old_v2.ts"]), 1)  # 缺原因
            self.assertEqual(audit.main([str(self.root), "--review", "version-suffix", "src/nope.ts",
                                         "--reason", "x"]), 1)  # 没有这条告警
            self.assertEqual(audit.main([str(self.root), "--review", "version-suffix", "src/old_v2.ts",
                                         "--reason", "第三方 SDK 的文件名"]), 0)
        cfg = json.loads((self.root / ".claude/tidy.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["layout"], LAYOUT["layout"])  # 原有配置保留
        findings, summary = audit.audit(self.root)
        self.assertNotIn("src/old_v2.ts", {f.path for f in findings})
        self.assertEqual(summary["reviewed"], 1)
        write(self.root, "src/old_v2.ts", "changed" * 20)
        findings, _ = audit.audit(self.root)
        f = [x for x in findings if x.path == "src/old_v2.ts"]
        self.assertTrue(f and "请复核" in f[0].message)

    def test_review_cannot_hide_secrets(self):
        write(self.root, "src/.env", "K=1")
        self.assertIn("密钥", audit.add_review(self.root, "secret-not-ignored", "src/.env", "x"))


class NonGitIgnoreTest(unittest.TestCase):
    def test_negation_and_double_star(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            write(root, ".gitignore", ".env*\n!.env.example\nvoice/**/*.mp3\n/out/\n")
            proj = rules.Project(root)
            self.assertFalse(proj.is_git)
            self.assertTrue(proj.is_ignored(".env", False))
            self.assertFalse(proj.is_ignored(".env.example", False))
            self.assertTrue(proj.is_ignored("voice/a.mp3", False))
            self.assertTrue(proj.is_ignored("voice/L1/a.mp3", False))
            self.assertFalse(proj.is_ignored("voice/a.wav", False))
            self.assertTrue(proj.is_ignored("out/x/y.mp4", False))
            self.assertFalse(proj.is_ignored("src/out/y.mp4", False))


if __name__ == "__main__":
    unittest.main()
