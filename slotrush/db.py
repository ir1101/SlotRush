"""Connection helpers for PostgreSQL (psycopg 3) and MongoDB (pymongo).

Every other module opens connections through these functions, so host, port and
credentials live in exactly one place (.env).
"""
import psycopg
from psycopg.conninfo import make_conninfo
from pymongo import MongoClient

from .config import read_env


def pg_conninfo(dbname: str | None = None, application_name: str = "slotrush") -> str:
    """Build a libpq connection string from .env.

    application_name shows up in pg_stat_activity, which lets the locking demo
    tell the bot sessions apart.
    """
    env = read_env()
    return make_conninfo(
        host=env["POSTGRES_HOST"],
        port=env["POSTGRES_PORT"],
        user=env["POSTGRES_USER"],
        password=env["POSTGRES_PASSWORD"],
        dbname=dbname or env["POSTGRES_DB"],
        application_name=application_name,
        connect_timeout=5,   # fail fast if the container is not running
    )


def pg_connect(dbname: str | None = None, autocommit: bool = False,
               application_name: str = "slotrush") -> psycopg.Connection:
    """Open one PostgreSQL connection.

    With autocommit=False (the default) psycopg starts a transaction at the first
    statement, and nothing is permanent until conn.commit().
    """
    return psycopg.connect(pg_conninfo(dbname, application_name), autocommit=autocommit)


def mongo_client(timeout_ms: int = 5000) -> MongoClient:
    """Return a MongoDB client. pymongo connects lazily, on the first command."""
    env = read_env()
    return MongoClient(
        host=env["MONGO_HOST"],
        port=int(env["MONGO_PORT"]),
        username=env["MONGO_USER"],
        password=env["MONGO_PASSWORD"],
        serverSelectionTimeoutMS=timeout_ms,   # fail fast if the container is not running
    )
