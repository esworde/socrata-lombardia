import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).parents[1] / "install.py"
SPEC = importlib.util.spec_from_file_location("skill_installer", SCRIPT)
skill_installer = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = skill_installer
SPEC.loader.exec_module(skill_installer)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name) / "home"
        self.source = Path(self.temp.name) / "source"
        (self.source / "scripts").mkdir(parents=True)
        (self.source / "SKILL.md").write_text("---\nname: fetch-portale-pagamenti\ndescription: Test\n---\n")
        (self.source / "scripts/export.py").write_text("print('ok')\n")

    def tearDown(self):
        self.temp.cleanup()

    def prepare_existing_codex_install(self):
        unrelated = self.home / ".codex/skills/other/SKILL.md"
        unrelated.parent.mkdir(parents=True)
        unrelated.write_text("keep")
        target = self.home / ".codex/skills/fetch-portale-pagamenti"
        target.mkdir(parents=True)
        (target / "old.txt").write_text("old")
        return target, unrelated

    def assert_prior_install_preserved(self, target, unrelated):
        self.assertEqual((target / "old.txt").read_text(), "old")
        self.assertEqual(unrelated.read_text(), "keep")
        self.assertFalse(list(target.parent.glob(".fetch-portale-pagamenti.tmp-*")))
        self.assertFalse(list(target.parent.glob(".fetch-portale-pagamenti.backup-*")))

    def test_installs_each_supported_agent(self):
        expected = {
            "codex": self.home / ".codex/skills/fetch-portale-pagamenti",
            "claude": self.home / ".claude/skills/fetch-portale-pagamenti",
            "cursor": self.home / ".cursor/skills/fetch-portale-pagamenti",
        }
        for agent, target in expected.items():
            installed = skill_installer.install_skill(agent, self.home, self.source)
            self.assertEqual(installed, (target,))
            self.assertEqual((target / "SKILL.md").read_text(), (self.source / "SKILL.md").read_text())

    def test_all_installs_three_identical_copies(self):
        targets = skill_installer.install_skill("all", self.home, self.source)
        self.assertEqual(len(targets), 3)
        self.assertEqual({(target / "SKILL.md").read_text() for target in targets}, {(self.source / "SKILL.md").read_text()})

    def test_replaces_only_named_skill_and_preserves_unrelated_files(self):
        target, unrelated = self.prepare_existing_codex_install()
        skill_installer.install_skill("codex", self.home, self.source)
        self.assertEqual(unrelated.read_text(), "keep")
        self.assertFalse((target / "old.txt").exists())
        self.assertTrue((target / "scripts/export.py").exists())

    def test_copy_failure_cleans_partial_copy_and_preserves_prior_install(self):
        target, unrelated = self.prepare_existing_codex_install()

        def fail_after_partial_copy(_source, temporary):
            temporary.mkdir()
            (temporary / "partial.txt").write_text("partial")
            raise OSError("copy failed")

        with patch.object(skill_installer.shutil, "copytree", side_effect=fail_after_partial_copy):
            with self.assertRaisesRegex(OSError, "copy failed"):
                skill_installer.install_skill("codex", self.home, self.source)

        self.assert_prior_install_preserved(target, unrelated)

    def test_promotion_failure_preserves_prior_install(self):
        target, unrelated = self.prepare_existing_codex_install()
        original_rename = Path.rename

        def fail_promotion(path, destination):
            if path.name.startswith(".fetch-portale-pagamenti.tmp-"):
                raise OSError("promotion failed")
            return original_rename(path, destination)

        with patch.object(Path, "rename", fail_promotion):
            with self.assertRaisesRegex(OSError, "promotion failed"):
                skill_installer.install_skill("codex", self.home, self.source)

        self.assert_prior_install_preserved(target, unrelated)

    def test_cleanup_failure_still_restores_prior_install(self):
        target, unrelated = self.prepare_existing_codex_install()
        original_rename = Path.rename
        original_rmtree = skill_installer.shutil.rmtree

        def fail_promotion(path, destination):
            if path.name.startswith(".fetch-portale-pagamenti.tmp-"):
                raise OSError("promotion failed")
            return original_rename(path, destination)

        def fail_after_cleanup(path):
            original_rmtree(path)
            if Path(path).name.startswith(".fetch-portale-pagamenti.tmp-"):
                raise OSError("cleanup failed")

        with (
            patch.object(Path, "rename", fail_promotion),
            patch.object(skill_installer.shutil, "rmtree", side_effect=fail_after_cleanup),
        ):
            with self.assertRaises(OSError):
                skill_installer.install_skill("codex", self.home, self.source)

        self.assert_prior_install_preserved(target, unrelated)

    def test_replaces_file_and_symlink_targets(self):
        for kind in ("file", "symlink"):
            with self.subTest(kind=kind):
                home = Path(self.temp.name) / kind
                target = home / ".codex/skills/fetch-portale-pagamenti"
                target.parent.mkdir(parents=True)
                if kind == "file":
                    target.write_text("old")
                else:
                    referent = home / "prior-skill"
                    referent.write_text("old")
                    target.symlink_to(referent)

                skill_installer.install_skill("codex", home, self.source)

                self.assertTrue((target / "scripts/export.py").is_file())
                self.assertFalse(list(target.parent.glob(".fetch-portale-pagamenti.backup-*")))
                if kind == "symlink":
                    self.assertEqual(referent.read_text(), "old")
