"""Database access for the web app: one connection pool, one role per request.

Every page runs its SQL inside ONE transaction that begins with

    SET LOCAL ROLE student_role;                         -- or faculty_role / admin_role
    SELECT set_config('app.reg_no', '23BCE0042', true);  -- who the student is

so PostgreSQL's row-level security decides what the page may see, exactly as
in tests/test_security.py. LOCAL (and the "true" in set_config) means both
settings end with the transaction, so a pooled connection can never carry one
user's identity into the next request.

This web server is the "trusted application layer" that makes app.reg_no safe:
the browser never sends SQL, and the server only sets app.reg_no to the student
chosen on the log-in page.

Every statement is also recorded in flask.g.queries for the "Queries" panel
shown at the bottom of each page.
"""
import textwrap
import time
from contextlib import contextmanager

from flask import g, has_request_context
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from ..db import pg_conninfo

# web role name -> PostgreSQL role (fixed strings, never user input)
ROLES = {"student": "student_role", "faculty": "faculty_role", "admin": "admin_role"}

_pool: ConnectionPool | None = None


def open_pool(dbname: str | None = None) -> None:
    """Create the pool once at start-up. A few connections are shared by all
    requests, instead of opening a new connection for every page."""
    global _pool
    # timeout: if no connection can be had within 5 s (database down), give up
    # with PoolTimeout instead of making the page hang.
    _pool = ConnectionPool(pg_conninfo(dbname, application_name="slotrush-web"),
                           min_size=1, max_size=8, timeout=5, open=True)


def close_pool() -> None:
    if _pool is not None:
        _pool.close()


def _record(role: str, sql: str, params, rows: int, ms: float) -> None:
    """Remember a statement for the Queries panel."""
    if has_request_context():
        g.setdefault("queries", []).append({
            "role": role, "sql": textwrap.dedent(sql).strip(),
            "params": list(params) if params else [], "rows": rows, "ms": ms})


class RoleSession:
    """A connection that is already inside a transaction, running as one role."""

    def __init__(self, conn, role: str):
        self.conn = conn
        self.role = role

    def all(self, sql: str, params=None) -> list[dict]:
        """Run a query and return every row as a dict (column name -> value)."""
        started = time.perf_counter()
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall() if cur.description else []
        _record(self.role, sql, params, len(rows), (time.perf_counter() - started) * 1000)
        return rows

    def one(self, sql: str, params=None) -> dict | None:
        rows = self.all(sql, params)
        return rows[0] if rows else None

    def value(self, sql: str, params=None):
        """The first column of the first row (or None)."""
        row = self.one(sql, params)
        return next(iter(row.values())) if row else None


@contextmanager
def as_role(role: str, reg_no: str | None = None, faculty_id: int | None = None):
    """Run the block in one transaction as the given role. Commits if the block
    finishes, rolls back if it raises."""
    with _pool.connection() as conn:
        with conn.transaction():
            session = RoleSession(conn, ROLES[role])
            session.all(f"SET LOCAL ROLE {ROLES[role]}")
            if reg_no is not None:
                session.all("SELECT set_config('app.reg_no', %s, true)", (reg_no,))
            if faculty_id is not None:
                session.all("SELECT set_config('app.faculty_id', %s, true)", (str(faculty_id),))
            yield session
