"""Single entry point:  python -m slotrush <command>

Run "python -m slotrush --help" for the list. Imports happen inside each
branch so that, for example, "up" works before any database exists.
"""
import argparse
import subprocess
import sys

from .config import RESULTS_DIR, ROOT

COMMANDS = [
    # (name, help text)
    ("up", "start PostgreSQL and MongoDB in Docker and wait until healthy"),
    ("down", "stop the containers (add --wipe to delete all data)"),
    ("check", "check both database connections and key settings"),
    ("setup", "drop and rebuild the schema (tables, functions, views, roles, RLS)"),
    ("load", "setup + generate the synthetic data + COPY it in + check-data"),
    ("check-data", "prove the loaded data obeys every rule"),
    ("nulls", "show how NULL behaves, using offering.venue"),
    ("lost-update", "demo 1: 80 bots, 30 seats, naive path at READ COMMITTED"),
    ("locking", "demo 2: the same race through register() and FOR UPDATE"),
    ("serializable", "demo 3: naive path at SERIALIZABLE with retries + comparison chart"),
    ("deadlock", "demo 4: opposite moves deadlock; swap_course does not"),
    ("crash", "demo 5: kill PostgreSQL mid-run and check durability (add --async-commit)"),
    ("bench", "five queries x three index setups, plans and timings"),
    ("normalise", "flat export, FD checks and lossless-join checks (1NF to 5NF)"),
    ("reviews", "seed MongoDB reviews, index explain, aggregations"),
    ("web", "start the web front end on http://127.0.0.1:5000"),
    ("test", "run pytest and save the report to results/pytest_report.txt"),
    ("review", "run every demo in order, pausing for Enter between them"),
]


def run_tests() -> int:
    """Run pytest in a child process and save everything it prints."""
    result = subprocess.run([sys.executable, "-m", "pytest", "-v"], cwd=ROOT,
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(result.stdout, result.stderr, sep="")
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "pytest_report.txt").write_text(result.stdout + result.stderr, encoding="utf-8")
    print("Saved to results/pytest_report.txt")
    return result.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m slotrush",
        description="SlotRush: FFCS-style course registration demos for BCSE302L.",
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="<command>")
    sub = {name: commands.add_parser(name, help=text) for name, text in COMMANDS}
    sub["down"].add_argument("--wipe", action="store_true",
                             help="also delete the data volumes (all loaded data is lost)")
    sub["setup"].add_argument("--test", action="store_true",
                              help="build the schema in the test database instead")
    sub["crash"].add_argument("--async-commit", action="store_true",
                              help="bots use synchronous_commit = off (check (a) may FAIL)")
    sub["web"].add_argument("--port", type=int, default=5000, help="port to listen on")
    sub["review"].add_argument("--no-pause", action="store_true", help="do not wait for Enter")
    sub["review"].add_argument("--start", type=int, default=1, help="start at this step number")
    args = parser.parse_args(argv)

    if args.command == "up":
        from . import containers
        return containers.up()
    if args.command == "down":
        from . import containers
        return containers.down(wipe=args.wipe)
    if args.command == "check":
        from . import check
        return check.run()
    if args.command == "setup":
        from . import setup_db
        return setup_db.run(test=args.test)
    if args.command == "load":
        from . import load
        return load.run()
    if args.command == "check-data":
        from . import check_data
        return check_data.run()
    if args.command == "nulls":
        from . import nulls
        return nulls.run()
    if args.command == "lost-update":
        from .demos import lost_update
        return lost_update.run()
    if args.command == "locking":
        from .demos import locking
        return locking.run()
    if args.command == "serializable":
        from .demos import serializable
        return serializable.run()
    if args.command == "deadlock":
        from .demos import deadlock
        return deadlock.run()
    if args.command == "crash":
        from .demos import crash
        return crash.run(async_commit=args.async_commit)
    if args.command == "bench":
        from . import bench
        return bench.run()
    if args.command == "normalise":
        from . import normalise
        return normalise.run()
    if args.command == "reviews":
        from . import nosql
        return nosql.run()
    if args.command == "web":
        from .web import app
        return app.run(port=args.port)
    if args.command == "test":
        return run_tests()
    if args.command == "review":
        from . import review
        return review.run(pause=not args.no_pause, start=args.start)
    return 1   # not reached: argparse rejects unknown commands


if __name__ == "__main__":
    raise SystemExit(main())
