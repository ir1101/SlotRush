"""The 'check' command: prove both databases are reachable.

It also prints the PostgreSQL settings the later demos depend on, and saves the
whole report to results/phase0_connection_check.txt for the project report.
"""
from datetime import datetime

import psycopg
from pymongo.errors import PyMongoError

from .config import RESULTS_DIR, read_env
from .db import mongo_client, pg_connect

REPORT_FILE = RESULTS_DIR / "phase0_connection_check.txt"

# PostgreSQL settings to show, in this order.
PG_SETTINGS = [
    "server_version",
    "fsync",                          # flush WAL to disk at commit (crash demo)
    "synchronous_commit",             # COMMIT waits for that flush (crash demo)
    "full_page_writes",               # protects against torn pages after a crash
    "wal_level",
    "max_connections",                # raised to 200 in docker-compose.yml
    "default_transaction_isolation",  # READ COMMITTED unless a demo changes it
    "deadlock_timeout",               # how long a lock wait lasts before the deadlock check
    "log_lock_waits",
]

# Values the demos rely on. A mismatch is reported as a warning.
EXPECTED = {
    "fsync": "on",
    "synchronous_commit": "on",
    "max_connections": "200",
}


def check_postgres(report: list[str]) -> bool:
    """Connect, read the settings and append them to the report. Returns True on success."""
    env = read_env()
    where = f"{env['POSTGRES_HOST']}:{env['POSTGRES_PORT']}/{env['POSTGRES_DB']}"
    try:
        with pg_connect() as conn:
            report.append(f"PostgreSQL  {where}  OK")
            report.append(f"  {conn.execute('SELECT version()').fetchone()[0]}")
            for name in PG_SETTINGS:
                # current_setting() takes the name as a normal parameter: no string-built SQL.
                value = conn.execute("SELECT current_setting(%s)", (name,)).fetchone()[0]
                line = f"  {name:<30} {value}"
                if name in EXPECTED and value != EXPECTED[name]:
                    line += f"   WARNING: expected {EXPECTED[name]}"
                report.append(line)
        return True
    except psycopg.OperationalError as exc:
        report.append(f"PostgreSQL  {where}  FAILED")
        report.append(f"  {str(exc).strip()}")
        return False


def check_mongo(report: list[str]) -> bool:
    """Ping MongoDB and append its version to the report. Returns True on success."""
    env = read_env()
    where = f"{env['MONGO_HOST']}:{env['MONGO_PORT']}"
    client = mongo_client()
    try:
        client.admin.command("ping")
        report.append(f"MongoDB     {where}  OK")
        report.append(f"  {'version':<30} {client.server_info()['version']}")
        return True
    except PyMongoError as exc:
        report.append(f"MongoDB     {where}  FAILED")
        # pymongo's messages are very long; the first 150 characters say what went wrong.
        report.append(f"  {str(exc)[:150]}...")
        return False
    finally:
        client.close()


def run() -> int:
    """Run both checks, print the report, save it, and return a process exit code."""
    report = [f"SlotRush connection check, {datetime.now():%Y-%m-%d %H:%M:%S}", ""]
    pg_ok = check_postgres(report)
    report.append("")
    mongo_ok = check_mongo(report)
    report.append("")
    if pg_ok and mongo_ok:
        report.append("Result: both databases are reachable.")
    else:
        report.append("Result: FAILED. Start the containers with: python -m slotrush up")

    text = "\n".join(report)
    print(text)
    RESULTS_DIR.mkdir(exist_ok=True)
    REPORT_FILE.write_text(text + "\n", encoding="utf-8")
    print(f"\nSaved to {REPORT_FILE.relative_to(RESULTS_DIR.parent)}")
    return 0 if pg_ok and mongo_ok else 1
