"""Single entry point:  python -m slotrush <command>

Commands so far (Phase 0):
  up      start PostgreSQL and MongoDB in Docker and wait until both are healthy
  down    stop the containers (add --wipe to also delete all data)
  check   connect to both databases and save results/phase0_connection_check.txt
"""
import argparse

from . import check, containers


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m slotrush",
        description="SlotRush: FFCS-style course registration demos for BCSE302L.",
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="<command>")
    commands.add_parser("up", help="start PostgreSQL and MongoDB and wait until healthy")
    down = commands.add_parser("down", help="stop the containers")
    down.add_argument("--wipe", action="store_true",
                      help="also delete the data volumes (all loaded data is lost)")
    commands.add_parser("check", help="check both database connections")

    args = parser.parse_args(argv)
    if args.command == "up":
        return containers.up()
    if args.command == "down":
        return containers.down(wipe=args.wipe)
    if args.command == "check":
        return check.run()
    return 1   # not reached: argparse rejects unknown commands


if __name__ == "__main__":
    raise SystemExit(main())
