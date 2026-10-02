"""Programmatic Alembic entry points; the migrations ship inside the package.

python -m sahifa.db.migrate upgrade [head]
python -m sahifa.db.migrate downgrade base
python -m sahifa.db.migrate current
python -m sahifa.db.migrate check
"""

from __future__ import annotations

import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from sahifa.settings import get_settings

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def build_config(database_url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    # ConfigParser interpolation: a literal % in a password must be doubled.
    cfg.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return cfg


def head_revision() -> str:
    heads = ScriptDirectory(str(MIGRATIONS_DIR)).get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"expected exactly one migration head, found {heads}")
    return heads[0]


def upgrade(database_url: str, revision: str = "head") -> None:
    command.upgrade(build_config(database_url), revision)


def downgrade(database_url: str, revision: str) -> None:
    command.downgrade(build_config(database_url), revision)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args or args[0] not in {"upgrade", "downgrade", "current", "check"}:
        print("usage: python -m sahifa.db.migrate upgrade [rev] | downgrade <rev> | current | check")  # noqa: T201
        return 2
    url = get_settings().migration_url
    if args[0] == "upgrade":
        upgrade(url, args[1] if len(args) > 1 else "head")
    elif args[0] == "downgrade":
        if len(args) < 2:
            print("downgrade needs a revision, e.g. base")  # noqa: T201
            return 2
        downgrade(url, args[1])
    elif args[0] == "current":
        command.current(build_config(url))
    else:
        command.check(build_config(url))
    return 0


if __name__ == "__main__":
    sys.exit(main())
