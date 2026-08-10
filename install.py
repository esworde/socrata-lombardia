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
        shutil.copytree(source, temporary)
        had_target = target.exists()
        try:
            if had_target:
                target.rename(backup)
            temporary.rename(target)
        except Exception:
            if temporary.exists():
                shutil.rmtree(temporary)
            if had_target and backup.exists():
                backup.rename(target)
            raise
        if backup.exists():
            shutil.rmtree(backup)
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
