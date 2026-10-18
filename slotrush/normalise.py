"""The 'normalise' command: evidence for the normalisation chapter.

  1. Export a flat, denormalised registration table to
     results/flat_registration_export.csv (phones packed into one field, so it
     is not even in 1NF).
  2. Check that the functional dependencies claimed in docs/normalisation.md
     really hold in that data, and compute attribute closures.
  3. Decompose step by step (1NF, 2NF, 3NF/BCNF), join the parts back with a
     natural join, and compare with the original: equal means lossless.
     A deliberately bad split shows what a lossy join looks like.
  4. A 4NF example (two independent multivalued dependencies) and a 5NF
     example (a join dependency), each checked the same way.

Relations are handled as Python sets of tuples, so "join back and compare"
is literally set equality. Output: results/normalisation_lossless_check.txt.
"""
import csv
from itertools import product

from .config import RESULTS_DIR
from .db import pg_connect

EXPORT_FILE = RESULTS_DIR / "flat_registration_export.csv"
REPORT_FILE = RESULTS_DIR / "normalisation_lossless_check.txt"
SAMPLE_STUDENTS = 500     # keeps the CSV small enough to open and to commit

FLAT_COLUMNS = ["reg_no", "first_name", "last_name", "programme", "phones",
                "offering_id", "semester", "course_code", "title", "credits", "course_type",
                "faculty_id", "faculty_name", "school", "slot_id", "venue", "capacity",
                "registered_at"]

FLAT_SQL = """
    SELECT s.reg_no, s.first_name, s.last_name, s.programme,
           (SELECT string_agg(p.phone, ';' ORDER BY p.phone)
            FROM student_phone p WHERE p.reg_no = s.reg_no) AS phones,
           o.offering_id, o.semester, c.course_code, c.title, c.credits, c.course_type,
           f.faculty_id, f.first_name || ' ' || f.last_name AS faculty_name, f.school,
           o.slot_id, o.venue, o.capacity, r.registered_at
    FROM registration r
    JOIN student s  ON s.reg_no = r.reg_no
    JOIN offering o ON o.offering_id = r.offering_id
    JOIN course c   ON c.course_code = o.course_code
    JOIN faculty f  ON f.faculty_id = o.faculty_id
    WHERE s.reg_no IN (SELECT reg_no FROM student WHERE programme <> 'BOT'
                       ORDER BY reg_no LIMIT %(limit)s)
    ORDER BY s.reg_no, o.offering_id
"""

# Functional dependencies of the 1NF relation (phone moved out): left side -> right side
FDS = [
    (["reg_no"], ["first_name", "last_name", "programme"]),
    (["course_code"], ["title", "credits", "course_type"]),
    (["faculty_id"], ["faculty_name", "school"]),
    (["offering_id"], ["semester", "course_code", "faculty_id", "slot_id", "venue", "capacity"]),
    (["reg_no", "offering_id"], ["registered_at"]),
]


# --------------------------------------------------------------------------- relational helpers

class Relation:
    """A relation = a heading (attribute names) + a SET of tuples (so no duplicates)."""

    def __init__(self, attrs, rows):
        self.attrs = list(attrs)
        self.rows = set(rows)

    def __len__(self):
        return len(self.rows)


def from_dicts(attrs, dicts) -> Relation:
    return Relation(attrs, (tuple(d[a] for a in attrs) for d in dicts))


def project(rel: Relation, attrs) -> Relation:
    """π attrs (rel): keep some columns; the set removes duplicate rows."""
    idx = [rel.attrs.index(a) for a in attrs]
    return Relation(attrs, (tuple(row[i] for i in idx) for row in rel.rows))


def natural_join(left: Relation, right: Relation) -> Relation:
    """left ⋈ right on all attributes with the same name (a hash join)."""
    common = [a for a in left.attrs if a in right.attrs]
    extra = [a for a in right.attrs if a not in common]
    l_idx = [left.attrs.index(a) for a in common]
    r_idx = [right.attrs.index(a) for a in common]
    e_idx = [right.attrs.index(a) for a in extra]
    buckets = {}                                   # join key -> matching right rows
    for row in right.rows:
        buckets.setdefault(tuple(row[i] for i in r_idx), []).append(row)
    out = set()
    for row in left.rows:
        for match in buckets.get(tuple(row[i] for i in l_idx), []):
            out.add(row + tuple(match[i] for i in e_idx))
    return Relation(left.attrs + extra, out)


def join_all(parts) -> Relation:
    result = parts[0]
    for part in parts[1:]:
        result = natural_join(result, part)
    return result


def same_relation(a: Relation, b: Relation) -> bool:
    """Equal sets of tuples, after putting b's columns in a's order."""
    return set(a.attrs) == set(b.attrs) and project(b, a.attrs).rows == a.rows


def lossless_check(report, name, original: Relation, parts) -> bool:
    joined = join_all(parts)
    ok = same_relation(original, joined)
    spurious = len(joined) - len(original) if set(joined.attrs) == set(original.attrs) else "?"
    heads = " ⋈ ".join(f"{len(p)}-row ({', '.join(p.attrs)})" for p in parts)
    report.append(f"  [{'LOSSLESS' if ok else 'LOSSY'}] {name}")
    report.append(f"      parts: {heads}")
    report.append(f"      original {len(original)} rows, joined back {len(joined)} rows, "
                  f"spurious {spurious}")
    return ok


def closure(attrs, fds) -> set:
    """Attribute closure X+ : keep applying FDs whose left side is already inside."""
    result = set(attrs)
    changed = True
    while changed:
        changed = False
        for lhs, rhs in fds:
            if set(lhs) <= result and not set(rhs) <= result:
                result |= set(rhs)
                changed = True
    return result


def fd_holds(rel: Relation, lhs, rhs) -> bool:
    """X -> Y holds if no two rows agree on X but differ on Y."""
    seen = {}
    for row in project(rel, lhs + rhs).rows:
        key, value = row[:len(lhs)], row[len(lhs):]
        if seen.setdefault(key, value) != value:
            return False
    return True


# --------------------------------------------------------------------------- the steps

def export() -> list[dict]:
    with pg_connect() as conn:
        cur = conn.execute(FLAT_SQL, {"limit": SAMPLE_STUDENTS})
        rows = cur.fetchall()
    with EXPORT_FILE.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(FLAT_COLUMNS)
        writer.writerows(rows)
    # Read it back as text, exactly as a spreadsheet user would see it.
    with EXPORT_FILE.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main_decomposition(report, flat_rows) -> bool:
    attrs_1nf = [a if a != "phones" else "phone" for a in FLAT_COLUMNS]
    # 0NF -> 1NF: one row per phone number, so every field holds one value.
    unnested = [dict(row, phone=phone) for row in flat_rows for phone in row["phones"].split(";")]
    r_1nf = from_dicts(attrs_1nf, unnested)
    report.append(f"Flat export: {len(flat_rows)} rows ({SAMPLE_STUDENTS} students). "
                  f"Unnested to 1NF (one phone per row): {len(r_1nf)} rows.")

    report.append("\nFunctional dependencies, checked against the data:")
    for lhs, rhs in FDS:
        verdict = "holds" if fd_holds(r_1nf, lhs, rhs) else "VIOLATED"
        report.append(f"  {', '.join(lhs)} -> {', '.join(rhs)}: {verdict}")
    phone_fd = fd_holds(r_1nf, ["reg_no", "offering_id"], ["phone"])
    report.append(f"  reg_no, offering_id -> phone: {'holds' if phone_fd else 'does NOT hold'} "
                  "(a student with 2 phones has 2 rows per class: phone is multivalued)")

    report.append("\nAttribute closures (using the FDs above):")
    for attrs in (["reg_no"], ["offering_id"], ["reg_no", "offering_id"],
                  ["reg_no", "offering_id", "phone"]):
        c = closure(attrs, FDS)
        is_key = c >= set(attrs_1nf)
        report.append(f"  {{{', '.join(attrs)}}}+ = {len(c)} of {len(attrs_1nf)} attributes"
                      + ("  -> superkey" if is_key else
                         f"  (missing: {', '.join(sorted(set(attrs_1nf) - c))})"))
    report.append("  Candidate key of the 1NF relation: {reg_no, offering_id, phone} "
                  "(no attribute can be dropped and stay a superkey).")

    report.append("\nDecomposition steps (each must be lossless):")
    student_phone = project(r_1nf, ["reg_no", "phone"])
    r_no_phone = project(r_1nf, [a for a in attrs_1nf if a != "phone"])
    ok = lossless_check(report, "1NF: move the multivalued phone into StudentPhone",
                        r_1nf, [r_no_phone, student_phone])

    student = project(r_no_phone, ["reg_no", "first_name", "last_name", "programme"])
    registration = project(r_no_phone, ["reg_no", "offering_id", "registered_at"])
    offering_wide = project(r_no_phone, ["offering_id", "semester", "course_code", "title",
                                         "credits", "course_type", "faculty_id", "faculty_name",
                                         "school", "slot_id", "venue", "capacity"])
    ok &= lossless_check(report, "2NF: remove partial dependencies on {reg_no, offering_id}",
                         r_no_phone, [registration, student, offering_wide])

    course = project(offering_wide, ["course_code", "title", "credits", "course_type"])
    faculty = project(offering_wide, ["faculty_id", "faculty_name", "school"])
    offering = project(offering_wide, ["offering_id", "semester", "course_code", "faculty_id",
                                       "slot_id", "venue", "capacity"])
    ok &= lossless_check(report, "3NF/BCNF: remove transitive dependencies through "
                         "course_code and faculty_id", offering_wide, [offering, course, faculty])

    ok &= lossless_check(report, "All six BCNF relations joined back = the 1NF relation",
                         r_1nf, [registration, student, student_phone, offering, course, faculty])

    report.append("\nDependency preservation: every FD fits inside one final relation:")
    finals = {"Student": student, "StudentPhone": student_phone, "Registration": registration,
              "Offering": offering, "Course": course, "Faculty": faculty}
    for lhs, rhs in FDS:
        home = [n for n, rel in finals.items() if set(lhs + rhs) <= set(rel.attrs)]
        report.append(f"  {', '.join(lhs)} -> {', '.join(rhs)}: in {home[0] if home else 'NONE'}")
        ok &= bool(home)

    report.append("\nFor contrast, a LOSSY split (the shared attribute slot_id is a key of neither part):")
    lossless_check(report, "(reg_no, slot_id) and (slot_id, offering_id, course_code)",
                   project(r_no_phone, ["reg_no", "slot_id", "offering_id", "course_code"]),
                   [project(r_no_phone, ["reg_no", "slot_id"]),
                    project(r_no_phone, ["slot_id", "offering_id", "course_code"])])
    return ok


def fourth_normal_form(report) -> bool:
    """FacultyPreference: expertise and preferred slots are INDEPENDENT facts about a
    faculty member, so the table must hold every combination of them."""
    expertise = {1001: ["Databases", "Networks", "Security"],
                 1002: ["Machine Learning", "Statistics", "Vision"],
                 1003: ["Compilers", "Algorithms"],
                 1004: ["Thermodynamics", "Robotics"]}
    slots = {1001: ["T01", "T09", "T11"], 1002: ["T03", "T04", "T12", "T13"],
             1003: ["T02", "T05", "T10"], 1004: ["T07", "T15"]}
    attrs = ["faculty_id", "expertise", "preferred_slot"]
    pref = Relation(attrs, ((f, e, s) for f in expertise for e, s in product(expertise[f], slots[f])))
    save_relation("nf4_faculty_preference.csv", pref)

    report.append("\n4NF example: FacultyPreference(faculty_id, expertise, preferred_slot)")
    report.append(f"  {len(pref)} rows. Its only candidate key is all three attributes, so it is "
                  "in BCNF (no non-trivial FD at all).")
    report.append("  MVDs: faculty_id ->> expertise and faculty_id ->> preferred_slot "
                  "(each faculty member's rows are the full product of the two lists).")
    report.append("  Anomaly: giving faculty 1002 one more expertise needs "
                  f"{len(slots[1002])} new rows, one per preferred slot.")
    fe = project(pref, ["faculty_id", "expertise"])
    fs = project(pref, ["faculty_id", "preferred_slot"])
    ok = lossless_check(report, "4NF split on the MVD", pref, [fe, fs])
    report.append(f"  Rows stored: {len(pref)} before, {len(fe) + len(fs)} after.")
    return ok


def fifth_normal_form(report) -> bool:
    """Eligibility(faculty, course, slot) with the rule: if a faculty member can teach a
    course, the course may run in a slot, and the faculty member is free in that slot,
    then the faculty member may teach that course in that slot. The data is the
    classic Elmasri-Navathe SUPPLY example with the names changed."""
    rows = [("Rao", "BCSE302L", "T01"), ("Rao", "BCSE303L", "T02"), ("Iyer", "BCSE302L", "T02"),
            ("Menon", "BCSE303L", "T03"), ("Iyer", "BMAT201L", "T01"), ("Iyer", "BCSE302L", "T01"),
            ("Rao", "BCSE302L", "T02")]
    elig = Relation(["faculty", "course", "slot"], rows)
    save_relation("nf5_eligibility.csv", elig)
    fc = project(elig, ["faculty", "course"])
    cs = project(elig, ["course", "slot"])
    fs = project(elig, ["faculty", "slot"])

    report.append("\n5NF example: Eligibility(faculty, course, slot), "
                  f"{len(elig)} rows, all-key, no MVDs:")
    ok = True
    for name, parts in (("two projections: (faculty, course) + (course, slot)", [fc, cs]),
                        ("two projections: (faculty, course) + (faculty, slot)", [fc, fs]),
                        ("two projections: (course, slot) + (faculty, slot)", [cs, fs])):
        ok &= not lossless_check(report, name, elig, parts)      # each must be LOSSY
    report.append("  Every two-way split is lossy, so no MVD holds and the table is in 4NF.")
    ok &= lossless_check(report, "three projections: join dependency *(FC, CS, FS)",
                         elig, [fc, cs, fs])
    report.append("  The three-way split is lossless: the join dependency holds, so the table "
                  "is not in 5NF until it is split into all three.")
    return ok


def save_relation(name: str, rel: Relation) -> None:
    with (RESULTS_DIR / name).open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(rel.attrs)
        writer.writerows(sorted(rel.rows))


def run() -> int:
    flat_rows = export()
    report = [f"Exported {len(flat_rows)} rows to results/{EXPORT_FILE.name}", ""]
    ok = main_decomposition(report, flat_rows)
    ok &= fourth_normal_form(report)
    ok &= fifth_normal_form(report)
    report.append("\nResult: " + ("every expected check PASSED" if ok else "a check FAILED"))
    text = "\n".join(report)
    print(text)
    REPORT_FILE.write_text(text + "\n", encoding="utf-8")
    print(f"\nSaved to results/{REPORT_FILE.name}, results/nf4_faculty_preference.csv, "
          "results/nf5_eligibility.csv")
    return 0 if ok else 1
