import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/project-hygiene/scripts"
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
            write(root, ".claude/hygiene.json", json.dumps(LAYOUT))
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
            cfg = json.loads((root / ".claude/hygiene.json").read_text(encoding="utf-8"))
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
        write(self.root, ".claude/hygiene.json", json.dumps(LAYOUT))
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

    def test_hooks_can_be_disabled(self):
        write(self.root, ".claude/hygiene.json", json.dumps({"hooks": False}))
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


if __name__ == "__main__":
    unittest.main()
