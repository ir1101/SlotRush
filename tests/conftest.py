"""Shared pytest fixtures.

If a database is not reachable the test FAILS with a one-line hint instead of a
long traceback. It is not skipped, so a missing database can never look like a pass.
"""
import psycopg
import pytest
from pymongo.errors import PyMongoError

from slotrush.db import mongo_client, pg_connect


@pytest.fixture
def pg():
    """An open PostgreSQL connection, closed after the test."""
    conn, reason = None, ""
    try:
        conn = pg_connect()
    except psycopg.OperationalError as exc:
        reason = str(exc).strip()
    # Fail outside the except block so pytest prints one short message, not two tracebacks.
    if conn is None:
        pytest.fail(f"PostgreSQL is not reachable ({reason}). Run: python -m slotrush up",
                    pytrace=False)
    yield conn
    conn.close()


@pytest.fixture
def mongo():
    """A MongoDB client that has answered a ping, closed after the test."""
    client, reason = mongo_client(), ""
    try:
        client.admin.command("ping")
    except PyMongoError as exc:
        reason = str(exc)[:150]   # pymongo's messages are very long
    if reason:
        client.close()
        pytest.fail(f"MongoDB is not reachable ({reason}...). Run: python -m slotrush up",
                    pytrace=False)
    yield client
    client.close()
