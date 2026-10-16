import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/project-hygiene/scripts"))
import audit  # noqa: E402


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


class CleanProjectTest(unittest.TestCase):
    def test_clean_project_has_no_findings(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            write(root, "README.md", "# demo\n\n- src/ 源码\n- docs/ 文档\n")
            write(root, ".gitignore", "node_modules/\nout/\n.env\n")
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
        self.assertIn(f[0].rule, {"artifact-not-ignored", "tracked-artifact"})

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
        self.assertIn("scratch-file", rules_for(self.findings, "test.py"))

    def test_misc(self):
        rules = {f.rule for f in self.findings}
        self.assertTrue({"multiple-lockfiles", "empty-file", "duplicate-file",
                         "mixed-naming", "readme-missing-dir"} <= rules)

    def test_fail_on_exit_code(self):
        self.assertEqual(audit.main([str(self.root), "--fail-on", "error"]), 1)
        self.assertEqual(audit.main([str(self.root)]), 0)


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
            rules = {(f.rule, f.path) for f in findings}
            self.assertIn(("not-git-repo", "."), rules)
            self.assertFalse(any(f.path.startswith(("node_modules", "out", "logs/run.log")) for f in findings))


if __name__ == "__main__":
    unittest.main()
