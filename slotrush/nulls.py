"""The 'nulls' command: how NULL behaves, shown on the real offering.venue column.

venue is NULL for offerings that have no room allotted yet. Each example
prints the SQL and its result; the whole run is saved to
results/null_behaviour.txt for the report.
"""
from .config import RESULTS_DIR
from .db import pg_connect

REPORT_FILE = RESULTS_DIR / "null_behaviour.txt"

EXAMPLES = [
    ("COUNT(*) counts rows; COUNT(column) skips NULLs",
     "SELECT count(*) AS all_offerings, count(venue) AS with_venue, "
     "count(*) - count(venue) AS venue_null FROM offering"),

    ("'= NULL' is never true (it is UNKNOWN); use IS NULL",
     "SELECT (SELECT count(*) FROM offering WHERE venue = NULL) AS equals_null, "
     "(SELECT count(*) FROM offering WHERE venue IS NULL) AS is_null"),

    ("Comparisons with NULL give NULL (unknown), even NULL = NULL",
     "SELECT NULL = NULL AS null_eq_null, NULL <> 'SJT101' AS null_ne_text, "
     "NULL IS NULL AS null_is_null"),

    ("Three-valued logic: unknown AND false = false, unknown OR true = true",
     "SELECT (NULL::boolean AND false) AS unknown_and_false, "
     "(NULL::boolean OR true) AS unknown_or_true, (NULL::boolean AND true) AS unknown_and_true"),

    ("NOT IN with a NULL in the list returns nothing",
     "SELECT room, room NOT IN (SELECT venue FROM offering) AS not_in_result "
     "FROM (VALUES ('ZZZ999')) AS v(room)"),

    ("... because 'ZZZ999' <> NULL is unknown. NOT EXISTS (or filtering NULLs) gives the intended answer",
     "SELECT (SELECT count(*) FROM (VALUES ('ZZZ999')) AS v(room) "
     "        WHERE room NOT IN (SELECT venue FROM offering)) AS not_in, "
     "(SELECT count(*) FROM (VALUES ('ZZZ999')) AS v(room) "
     "        WHERE NOT EXISTS (SELECT 1 FROM offering o WHERE o.venue = v.room)) AS not_exists, "
     "(SELECT count(*) FROM (VALUES ('ZZZ999')) AS v(room) "
     "        WHERE room NOT IN (SELECT venue FROM offering WHERE venue IS NOT NULL)) AS not_in_no_nulls"),

    ("UNIQUE (venue, semester, slot_id) lets many NULL-venue classes share one slot",
     "SELECT semester, slot_id, count(*) AS classes_with_null_venue FROM offering "
     "WHERE venue IS NULL GROUP BY semester, slot_id HAVING count(*) > 1 "
     "ORDER BY classes_with_null_venue DESC, slot_id LIMIT 5"),

    ("GROUP BY puts every NULL venue into ONE group, although NULL = NULL is not true",
     "SELECT venue, count(*) AS classes FROM offering WHERE slot_id = 'T05' "
     "GROUP BY venue ORDER BY count(*) DESC, venue LIMIT 3"),

    ("COALESCE replaces NULL for display",
     "SELECT offering_id, venue, COALESCE(venue, 'not allotted') AS shown_as "
     "FROM offering WHERE venue IS NULL ORDER BY offering_id LIMIT 3"),
]


def run() -> int:
    out = []
    with pg_connect() as conn:
        for title, query in EXAMPLES:
            cur = conn.execute(query)
            columns = [d.name for d in cur.description]
            rows = cur.fetchall()
            out.append(f"-- {title}")
            out.append(query + ";")
            out.append("   " + " | ".join(columns))
            for row in rows:
                out.append("   " + " | ".join("NULL" if v is None else str(v) for v in row))
            out.append("")
    text = "\n".join(out)
    print(text)
    REPORT_FILE.write_text(text, encoding="utf-8")
    print(f"Saved to results/{REPORT_FILE.name}")
    return 0
