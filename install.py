import argparse
import shutil
import uuid
from collections.abc import Sequence
from pathlib import Path

SKILL_NAME = "fetch-portale-pagamenti"
DEFAULT_SOURCE = Path(__file__).resolve().parent / "skills" / SKILL_NAME
AGENT_DIRS = {
    "codex": Path(".codex/skills"),
    "claude": Path(".claude/skills"),
    "cursor": Path(".cursor/skills"),
}


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _remove_path(path: Path) -> None:
    if not _path_exists(path):
        return
    if path.is_symlink() or path.is_file():
        path.unlink()
    else:
        shutil.rmtree(path)


def install_skill(agent: str, home: Path, source: Path = DEFAULT_SOURCE) -> tuple[Path, ...]:
    if not (source / "SKILL.md").is_file():
        raise FileNotFoundError(f"missing {source / 'SKILL.md'}")

    agents = AGENT_DIRS if agent == "all" else {agent: AGENT_DIRS[agent]}
    installed = []
    for directory in agents.values():
        target = home / directory / SKILL_NAME
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.parent / f".{SKILL_NAME}.tmp-{uuid.uuid4()}"
        backup = target.parent / f".{SKILL_NAME}.backup-{uuid.uuid4()}"
        had_target = _path_exists(target)
        moved_target = False
        try:
            shutil.copytree(source, temporary)
            if had_target:
                target.rename(backup)
                moved_target = True
            temporary.rename(target)
        except Exception:
            try:
                _remove_path(temporary)
            finally:
                if moved_target and _path_exists(backup):
                    if _path_exists(target):
                        _remove_path(target)
                    backup.rename(target)
                elif not had_target:
                    _remove_path(target)
            raise
        if moved_target:
            _remove_path(backup)
        installed.append(target)
    return tuple(installed)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", choices=(*AGENT_DIRS, "all"), required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        for target in install_skill(args.agent, Path.home()):
            print(target)
    except Exception as error:
        print(f"error: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
