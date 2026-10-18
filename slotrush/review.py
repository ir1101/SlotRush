"""The 'review' command: run every demo in order, pausing for Enter between them.

Meant for the live project review. Each step says which syllabus module it
shows. Use --no-pause to run straight through, --start N to begin at step N.
"""
from . import bench, check, check_data, normalise, nosql, nulls
from .demos import crash, deadlock, locking, lost_update, serializable

STEPS = [
    ("Connection check", "1 Architecture", check.run),
    ("Data check (rules hold in 258,514 registrations)", "2 Relational model and ER", check_data.run),
    ("NULL behaviour on offering.venue", "2 Relational model (SQL)", nulls.run),
    ("Lost update at READ COMMITTED", "5 Transactions / 6 Concurrency control", lost_update.run),
    ("Row locking with register()", "6 Concurrency control", locking.run),
    ("SERIALIZABLE with retries, and the comparison chart", "6 Concurrency control", serializable.run),
    ("Deadlock, then swap_course with ordered locking", "6 Concurrency control", deadlock.run),
    # The benchmark runs before the crash: a crash resets PostgreSQL's activity statistics
    # and empties its buffer cache, which would add noise to the timings.
    ("Index benchmark", "4 Indexing and query processing", bench.run),
    ("Crash and WAL recovery (docker kill)", "5 Transactions and recovery", crash.run),
    ("Normalisation and lossless joins", "3 Normalisation", normalise.run),
    ("MongoDB reviews", "7 NoSQL", nosql.run),
]


def run(pause: bool = True, start: int = 1) -> int:
    failures = []
    for number, (title, module, step) in enumerate(STEPS, start=1):
        if number < start:
            continue
        print("\n" + "=" * 78)
        print(f"Step {number}/{len(STEPS)}: {title}    [syllabus module {module}]")
        print("=" * 78)
        if step() != 0:
            failures.append(title)
        if pause and number < len(STEPS):
            input("\nPress Enter for the next step (Ctrl+C to stop) ...")
    print("\nReview finished." + (f" Steps that reported a failure: {', '.join(failures)}"
                                  if failures else " Every step succeeded."))
    return 1 if failures else 0
