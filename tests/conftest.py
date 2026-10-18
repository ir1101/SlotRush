"""Shared pytest fixtures.

If a database is not reachable the test FAILS with a one-line hint instead of a
long traceback. It is not skipped, so a missing database can never look like a pass.

Rule and security tests run in a separate database (<POSTGRES_DB>_test) that
is rebuilt once per test session, so they never touch the loaded data.
"""
import psycopg
import pytest
from pymongo.errors import PyMongoError

from slotrush import setup_db
from slotrush.db import mongo_client, pg_connect

from .fixtures import clear_fixture, insert_fixture


@pytest.fixture
def pg():
    """An open connection to the main database, closed after the test."""
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


@pytest.fixture(scope="session")
def test_db():
    """Build a fresh schema in the test database once per test session."""
    try:
        setup_db.run(test=True)
    except psycopg.OperationalError as exc:
        pytest.fail(f"PostgreSQL is not reachable ({exc}). Run: python -m slotrush up",
                    pytrace=False)
    return setup_db.test_db_name()


@pytest.fixture
def db(test_db):
    """A test-database connection holding the fixture data in an open transaction.

    Everything the test does is rolled back afterwards, so tests cannot affect
    each other. Use "with db.transaction():" around a statement that is expected
    to fail: that creates a savepoint, so the error does not abort the test's
    transaction.
    """
    conn = pg_connect(test_db)
    insert_fixture(conn)
    yield conn
    conn.rollback()
    conn.close()


@pytest.fixture
def committed(test_db):
    """Commit the fixture data for tests that need several connections.

    Returns a function that opens extra connections to the test database.
    All data is removed again after the test.
    """
    with pg_connect(test_db) as conn:
        clear_fixture(conn)
        insert_fixture(conn)
    opened = []

    def connect(autocommit=False):
        conn = pg_connect(test_db, autocommit=autocommit)
        opened.append(conn)
        return conn

    yield connect
    for conn in opened:
        conn.close()
    with pg_connect(test_db) as conn:
        clear_fixture(conn)
