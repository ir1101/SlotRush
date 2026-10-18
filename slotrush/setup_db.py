"""The 'setup' command: build the SlotRush schema from the files in sql/.

Everything lives in one PostgreSQL schema called "slotrush". Setup drops it
and builds it again from scratch, so it can be rerun at any time (all data in
that database is lost). Roles are server-wide and are only created once.
"""
from psycopg import sql

from .config import SQL_DIR, TEST_DB_SUFFIX, read_env
from .db import pg_connect

# Order matters: tables before functions, functions before the grants on them.
SQL_FILES = [
    "01_schema.sql",
    "02_reference_data.sql",
    "03_functions.sql",
    "04_views.sql",
    "05_security.sql",
    "06_indexes.sql",
]


def main_db_name() -> str:
    return read_env()["POSTGRES_DB"]


def test_db_name() -> str:
    return main_db_name() + TEST_DB_SUFFIX


def ensure_database(dbname: str) -> None:
    """Create the database if it does not exist yet.

    CREATE DATABASE cannot run inside a transaction, so this connection is in
    autocommit mode.
    """
    with pg_connect(autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,)).fetchone()
        if not exists:
            # Identifier() quotes the name safely; it cannot be a %s parameter.
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))


def build_schema(dbname: str) -> None:
    """Drop and rebuild schema slotrush in one transaction: all of it or none of it."""
    with pg_connect(dbname) as conn:      # leaving the block commits (or rolls back on error)
        conn.execute("DROP SCHEMA IF EXISTS slotrush CASCADE")
        conn.execute("CREATE SCHEMA slotrush")
        # SET LOCAL lasts until the end of this transaction only.
        conn.execute("SET LOCAL search_path = slotrush, public")
        for name in SQL_FILES:
            # No parameters are passed, so psycopg sends the whole file as one
            # simple query and PostgreSQL runs its statements in order.
            conn.execute((SQL_DIR / name).read_text(encoding="utf-8"))
        # Every NEW session on this database starts with this search_path,
        # including psql sessions opened by hand.
        conn.execute(sql.SQL("ALTER DATABASE {} SET search_path = slotrush, public")
                     .format(sql.Identifier(dbname)))


def run(test: bool = False) -> int:
    dbname = test_db_name() if test else main_db_name()
    ensure_database(dbname)
    build_schema(dbname)
    print(f"Schema slotrush built in database {dbname} from: {', '.join(SQL_FILES)}")
    return 0
