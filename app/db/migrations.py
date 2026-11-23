"""
Run the Alembic migrations from the application (ARQ-03).

create_app()'s lifespan calls run_migrations() through
AsyncConnection.run_sync(), so every start of the container (and every test
app) brings its database to the latest revision before serving requests.

Databases created before ARQ-03 have the tables but no alembic_version
table. They are stamped at the initial revision ("0001", the schema Equipo 1
delivered) and then upgraded, so no table is recreated and no data is lost.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, inspect

# Repository root: app/db/migrations.py -> parents[2].
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
ALEMBIC_INI: Path = PROJECT_ROOT / "alembic.ini"

# Revision that matches the schema create_all() used to build.
BASELINE_REVISION: str = "0001"


def alembic_config(connection: Connection) -> Config:
    """Alembic config that reuses the given connection instead of a new engine."""
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.attributes["connection"] = connection
    return config


def run_migrations(connection: Connection) -> None:
    """
    Stamp pre-Alembic databases, then upgrade to the latest revision.

    On SQLite this turns foreign key enforcement off for the connection
    (OPT-05), as SQLite's own procedure for altering tables requires: the batch
    migrations copy a table, drop the original and rename the copy, and with
    enforcement on, ``DROP TABLE users`` fails while ``tasks`` still points at
    it. The setting cannot be restored from here, because it is ignored inside
    a transaction: the caller must not reuse the connection afterwards.
    ``main.migrate`` discards the pool, so the next connections get the
    PRAGMAs again from the ``connect`` listener of ``db.session``.
    """
    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
    config = alembic_config(connection)
    tables = set(inspect(connection).get_table_names())
    if "users" in tables and "alembic_version" not in tables:
        command.stamp(config, BASELINE_REVISION)
    command.upgrade(config, "head")
