from pathlib import Path
from alembic.config import Config as AlembicConfig
from alembic import command

_ALEMBIC_CFG = AlembicConfig(str(Path(__file__).parent.parent / "alembic.ini"))


def run_migrations() -> None:
    """Upgrade the SQL schema to the latest revision."""
    command.upgrade(_ALEMBIC_CFG, "head")
