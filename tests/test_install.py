import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

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
        unrelated = self.home / ".codex/skills/other/SKILL.md"
        unrelated.parent.mkdir(parents=True)
        unrelated.write_text("keep")
        target = self.home / ".codex/skills/fetch-portale-pagamenti"
        target.mkdir(parents=True)
        (target / "old.txt").write_text("old")
        skill_installer.install_skill("codex", self.home, self.source)
        self.assertEqual(unrelated.read_text(), "keep")
        self.assertFalse((target / "old.txt").exists())
        self.assertTrue((target / "scripts/export.py").exists())
