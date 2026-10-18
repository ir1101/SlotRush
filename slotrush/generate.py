"""Synthetic data generator (pure Python, no database access).

Everything is drawn from ONE random.Random(SEED) and a Faker seeded with the
same SEED, and the code never iterates over a Python set (set order changes
between runs), so the same inputs always give exactly the same rows.

Registrations are generated here, in Python, obeying the same rules as
register(): no second offering of a course, no slot clash, prerequisites met,
credits within the maximum, and never more students than seats. Students are
processed in order of their registration time, first come first served.
"""
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from itertools import accumulate

from faker import Faker

from .config import SEED, SEMESTER


@dataclass
class Scale:
    """How much data to make. The defaults are the full project size."""
    students: int = 30_000
    offerings: int = 4_500
    faculty: int = 750
    # Each student aims for a random credit total in this range (max_credits is 27).
    min_target_credits: int = 12
    max_target_credits: int = 27
    # The brief asks for capacities 40-80, but 4,500 offerings x 60 seats is only
    # ~270,000 seats for ~250,000 registrations (93% full, not "comfortably above").
    # 50-90 gives ~315,000 seats, so the brief's registration count fits at ~80%.
    capacity_min: int = 50
    capacity_max: int = 90


MAX_CREDITS = 27            # must match settings.max_credits in sql/02_reference_data.sql

# Department -> (school, subject nouns used to build course titles)
DEPARTMENTS = {
    "BCSE": ("SCOPE", ["Programming", "Data Structures", "Algorithms", "Operating Systems",
                       "Computer Networks", "Database Systems", "Compiler Design",
                       "Machine Learning", "Cryptography", "Software Engineering"]),
    "BITE": ("SITE", ["Web Technologies", "Information Security", "Cloud Computing",
                      "Data Mining", "Mobile Computing", "Distributed Systems"]),
    "BECE": ("SENSE", ["Digital Logic", "Signals and Systems", "Microprocessors",
                       "VLSI Design", "Communication Systems", "Embedded Systems"]),
    "BEEE": ("SELECT", ["Circuit Theory", "Electrical Machines", "Power Systems",
                        "Control Systems", "Power Electronics", "Renewable Energy"]),
    "BMEE": ("SMEC", ["Thermodynamics", "Fluid Mechanics", "Machine Design",
                      "Manufacturing Processes", "Heat Transfer", "Robotics"]),
    "BCLE": ("SCE", ["Structural Analysis", "Surveying", "Geotechnics",
                     "Transportation Engineering", "Hydrology", "Concrete Technology"]),
    "BMAT": ("SAS", ["Calculus", "Linear Algebra", "Probability", "Discrete Mathematics",
                     "Complex Variables", "Numerical Methods"]),
    "BPHY": ("SAS", ["Engineering Physics", "Quantum Mechanics", "Optics",
                     "Materials Science", "Electromagnetics", "Semiconductor Physics"]),
    "BCHY": ("SAS", ["Engineering Chemistry", "Environmental Chemistry", "Polymer Science",
                     "Electrochemistry", "Nanomaterials", "Analytical Chemistry"]),
    "BHUM": ("SSL", ["Technical English", "Economics", "Ethics", "Psychology",
                     "Management", "Public Policy"]),
}
# Departments every programme takes courses from.
COMMON_DEPTS = ["BMAT", "BPHY", "BCHY", "BHUM"]

# Programme code in the reg_no -> (home department, share of students)
PROGRAMMES = {"BCE": ("BCSE", 35), "BIT": ("BITE", 15), "BEC": ("BECE", 15),
              "BEE": ("BEEE", 10), "BME": ("BMEE", 15), "BCL": ("BCLE", 10)}

LEVEL_PREFIX = {1: ["Introduction to", "Foundations of"], 2: ["", "Applied"],
                3: ["Advanced", "Applied"], 4: ["Topics in", "Advanced"]}
LAB_ROOM_TYPE = {"BCSE": "Computer", "BITE": "Computer", "BECE": "Electronics",
                 "BEEE": "Electrical", "BMEE": "Mechanical", "BCLE": "Civil",
                 "BMAT": "Computer", "BPHY": "Physics", "BCHY": "Chemistry", "BHUM": "Language"}
DELIVERABLES = ["Report and demo", "Prototype", "Research paper", "Design document"]

# admit year -> semesters already finished by FALL2026
SEMESTERS_DONE = {2025: 2, 2024: 4, 2023: 6, 2022: 8}

THEORY_BUILDINGS = ["SJT", "TT", "MB", "PRP", "SMV", "GDN"]
LAB_BUILDINGS = ["SJT", "TT", "MB", "PRP"]
NULL_VENUE_SHARE = 0.04     # 4% of offerings have no room allotted yet (venue NULL)

# Registration opens 6 July 2026 09:00 IST and stays open 48 hours.
WINDOW_START = datetime(2026, 7, 6, 9, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
WINDOW_HOURS = 48


@dataclass
class Course:
    code: str
    title: str
    credits: int
    ctype: str              # THEORY, LAB or PROJECT
    level: int              # 1..4, drives prerequisites and who may take it
    dept: str
    popularity: float
    prereqs: list = field(default_factory=list)


@dataclass
class Dataset:
    """Rows for every table, each row a tuple in the loader's COPY column order."""
    students: list
    phones: list
    faculty: list
    courses: list
    theory: list
    labs: list
    projects: list
    prerequisites: list
    completed: list
    offerings: list
    registrations: list
    target_credits: dict    # reg_no -> credits the student aimed for (for reporting)


def clean(name: str, limit: int = 15) -> str:
    """Letters only, lower case: safe for an email address."""
    return re.sub(r"[^a-z]", "", name.lower())[:limit] or "x"


# --------------------------------------------------------------------------- courses

def make_courses(rng: random.Random) -> list[Course]:
    """60 courses per department: 36 theory (9 per level), 18 labs, 6 projects."""
    courses = []
    for dept, (_, nouns) in DEPARTMENTS.items():
        used_titles = {}
        for level in range(1, 5):
            for i in range(1, 10):
                base = f"{rng.choice(LEVEL_PREFIX[level])} {rng.choice(nouns)}".strip()
                used_titles[base] = used_titles.get(base, 0) + 1
                title = base if used_titles[base] == 1 else f"{base} {'I' * used_titles[base]}"
                credits = rng.choices([2, 3, 4], weights=[15, 60, 25])[0]
                courses.append(Course(f"{dept}{level}{i:02d}L", title, credits, "THEORY",
                                      level, dept, rng.lognormvariate(0, 0.5)))
        # Labs pair with theory courses 1-6 of levels 1-3 (same digits, suffix P).
        theory_by_code = {c.code: c for c in courses if c.dept == dept}
        for level in range(1, 4):
            for i in range(1, 7):
                theory = theory_by_code[f"{dept}{level}{i:02d}L"]
                credits = rng.choices([1, 2], weights=[70, 30])[0]
                courses.append(Course(f"{dept}{level}{i:02d}P", f"{theory.title} Lab", credits,
                                      "LAB", level, dept, rng.lognormvariate(0, 0.5)))
        # Projects at levels 3 and 4, numbered 91-93.
        for level in (3, 4):
            for i in range(91, 94):
                credits = rng.choice([2, 3])
                courses.append(Course(f"{dept}{level}{i}J", f"{dept[1:]} Project {level}{i}",
                                      credits, "PROJECT", level, dept, rng.lognormvariate(0, 0.5)))
    add_prerequisites(rng, courses)
    return courses


def add_prerequisites(rng: random.Random, courses: list[Course]) -> None:
    """Prerequisites always point to a LOWER level, so they can never form a cycle."""
    theory_by_dept_level = {}
    for c in courses:
        if c.ctype == "THEORY":
            theory_by_dept_level.setdefault((c.dept, c.level), []).append(c.code)
    for c in courses:
        if c.level == 1:
            continue
        lower = theory_by_dept_level[(c.dept, c.level - 1)]
        if c.ctype == "PROJECT" or rng.random() < 0.35:
            c.prereqs.append(rng.choice(lower))
        if c.level >= 3 and rng.random() < 0.10:
            second = rng.choice(theory_by_dept_level[(c.dept, c.level - 2)])
            if second not in c.prereqs:
                c.prereqs.append(second)


# --------------------------------------------------------------------------- weights

def affinity(programme: str, dept: str) -> float:
    """How likely a student of this programme is to pick a course of this department."""
    if PROGRAMMES[programme][0] == dept:
        return 3.0
    if dept in COMMON_DEPTS:
        return 1.5
    return 0.15


def demand_weight(course: Course) -> float:
    """Expected demand: used both to size the number of offerings and to pick courses,
    so supply roughly follows demand."""
    level_factor = {1: 1.3, 2: 1.2, 3: 1.0, 4: 0.8}[course.level]
    programme_mix = sum(share * affinity(p, course.dept) for p, (_, share) in PROGRAMMES.items())
    return course.popularity * level_factor * programme_mix


# --------------------------------------------------------------------------- people

def make_faculty(rng, fake, scale: Scale, courses: list[Course]) -> list[tuple]:
    """faculty_id 1001.., shared out between departments in proportion to the
    demand for their courses. Returns (id, first, last, dept)."""
    dept_weight = {d: 0.0 for d in DEPARTMENTS}
    for c in courses:
        dept_weight[c.dept] += demand_weight(c)
    total = sum(dept_weight.values())
    # Largest-remainder rounding: whole parts first, then the leftover seats go
    # to the departments with the biggest fractional parts. Sums to scale.faculty.
    exact = {d: scale.faculty * w / total for d, w in dept_weight.items()}
    counts = {d: int(x) for d, x in exact.items()}
    by_fraction = sorted(exact, key=lambda d: exact[d] - counts[d], reverse=True)
    for d in by_fraction[:scale.faculty - sum(counts.values())]:
        counts[d] += 1
    depts = [d for d in DEPARTMENTS for _ in range(counts[d])]
    people = []
    for n, dept in enumerate(depts):
        first, last = fake.first_name()[:40], fake.last_name()[:40]
        people.append((1001 + n, first, last, dept))
    return people


def make_students(rng, fake, scale: Scale) -> list[tuple]:
    """Returns (reg_no, first, last, programme, admit_year)."""
    programmes = list(PROGRAMMES)
    shares = [PROGRAMMES[p][1] for p in programmes]
    years = list(SEMESTERS_DONE)
    next_seq = {}
    students = []
    for _ in range(scale.students):
        programme = rng.choices(programmes, weights=shares)[0]
        year = rng.choice(years)
        next_seq[(year, programme)] = next_seq.get((year, programme), 0) + 1
        reg_no = f"{year % 100:02d}{programme}{next_seq[(year, programme)]:04d}"
        students.append((reg_no, fake.first_name()[:40], fake.last_name()[:40], programme, year))
    return students


def make_phones(rng, reg_no: str) -> list[tuple]:
    """1 to 3 Indian mobile numbers per student (the multivalued attribute)."""
    count = rng.choices([1, 2, 3], weights=[70, 25, 5])[0]
    phones = []
    while len(phones) < count:
        phone = f"+91{rng.choice('6789')}{rng.randrange(10**9):09d}"
        if phone not in phones:
            phones.append(phone)
    return [(reg_no, p) for p in phones]


# --------------------------------------------------------------------------- offerings

def make_offerings(rng, courses, faculty, slot_cells, slot_kind, demand, scale: Scale):
    """Decide how many offerings each course gets, then give each one a slot,
    a faculty member who is free in that slot, a venue and a capacity."""
    # 1. Offerings per course, proportional to the dry-run demand, at least 1 each.
    weights = [demand[c.code] + 1 for c in courses]
    total = sum(weights)
    counts = [max(1, round(scale.offerings * w / total)) for w in weights]
    # Fix rounding so the total is exactly scale.offerings: adjust the biggest courses.
    order = sorted(range(len(courses)), key=lambda i: -counts[i])
    k = 0
    while sum(counts) != scale.offerings:
        i = order[k % len(order)]
        if sum(counts) > scale.offerings and counts[i] > 1:
            counts[i] -= 1
        elif sum(counts) < scale.offerings:
            counts[i] += 1
        k += 1

    theory_slots = sorted(s for s in slot_kind if slot_kind[s] == "THEORY")
    lab_slots = sorted(s for s in slot_kind if slot_kind[s] == "LAB")
    slot_load = {s: 0 for s in slot_kind}
    rooms = {
        "THEORY": [f"{b}{floor}{room:02d}" for b in THEORY_BUILDINGS
                   for floor in range(1, 6) for room in range(1, 11)],     # 300 rooms
        "LAB": [f"{b}L{n:02d}" for b in LAB_BUILDINGS for n in range(1, 31)],  # 120 labs
    }
    next_room = {s: 0 for s in slot_kind}

    faculty_by_dept = {}
    for fid, _, _, dept in faculty:
        faculty_by_dept.setdefault(dept, []).append(fid)
    faculty_cells = {fid: set() for fid, *_ in faculty}   # (day, period) each person teaches
    faculty_load = {fid: 0 for fid, *_ in faculty}

    offerings = []          # (id, code, faculty_id, slot_id, semester, venue, capacity, seats_left)
    offering_id = 0
    for course, count in zip(courses, counts):
        slots = lab_slots if course.ctype == "LAB" else theory_slots
        # Least-used slots first; random tie-break keeps the spread even.
        ranked = sorted(slots, key=lambda s: (slot_load[s], rng.random()))
        chosen = [ranked[i % len(ranked)] for i in range(count)]
        for slot_id in chosen:
            cells = slot_cells[slot_id]
            # A faculty member of the course's department who is free in this slot.
            candidates = sorted(faculty_by_dept[course.dept],
                                key=lambda f: (faculty_load[f], rng.random()))
            free = [f for f in candidates if not (faculty_cells[f] & cells)]
            if not free:   # whole department busy: borrow anyone free
                free = sorted((f for f in faculty_cells if not (faculty_cells[f] & cells)),
                              key=lambda f: (faculty_load[f], rng.random()))
            fid = free[0]
            faculty_cells[fid] |= cells
            faculty_load[fid] += 1

            kind = slot_kind[slot_id]
            if rng.random() < NULL_VENUE_SHARE:
                venue = None
            else:
                venue = rooms[kind][next_room[slot_id]]
                next_room[slot_id] += 1

            offering_id += 1
            capacity = rng.randint(scale.capacity_min, scale.capacity_max)
            slot_load[slot_id] += 1
            offerings.append((offering_id, course.code, fid, slot_id, SEMESTER,
                              venue, capacity, capacity))
    return offerings


# --------------------------------------------------------------------------- history

def make_completed(rng, students, courses_by_code, pools):
    """Courses each student passed in earlier semesters. Prerequisites are always
    added before the courses that need them."""
    grades, grade_weights = ["S", "A", "B", "C", "D", "E"], [10, 25, 30, 20, 10, 5]
    completed = {}          # reg_no -> set of course codes (membership only, never iterated)
    rows = []
    for reg_no, _, _, programme, year in students:
        done = SEMESTERS_DONE[year]
        max_level = done // 2
        wanted = 3 * done
        codes, cum = pools[(programme, max_level, "history")]
        picks = rng.choices(codes, cum_weights=cum, k=wanted * 3)
        picks.sort(key=lambda code: courses_by_code[code].level)   # lower levels first
        passed = set()
        for code in picks:
            if len(passed) >= wanted:
                break
            course = courses_by_code[code]
            if code in passed or not all(p in passed for p in course.prereqs):
                continue
            passed.add(code)
            semester = f"FALL{year + course.level - 1}"
            rows.append((reg_no, code, semester, rng.choices(grades, grade_weights)[0]))
        completed[reg_no] = passed
    return completed, rows


def build_pools(courses):
    """Weighted course lists per (programme, max level, purpose), with cumulative
    weights so rng.choices can sample quickly."""
    pools = {}
    for programme in PROGRAMMES:
        for max_level in range(1, 5):
            for purpose in ("history", "register"):
                eligible = [c for c in courses
                            if c.level <= max_level
                            and (purpose == "register" or c.ctype != "PROJECT")]
                weights = [demand_weight(c) * affinity(programme, c.dept) for c in eligible]
                pools[(programme, max_level, purpose)] = (
                    [c.code for c in eligible], list(accumulate(weights)))
    return pools


# --------------------------------------------------------------------------- registrations

CANDIDATE_DRAWS = 120       # courses a student considers before giving up


def estimate_demand(rng, students, courses_by_code, completed, pools, scale: Scale) -> dict:
    """Dry run with unlimited seats and no timetable: how many students would
    pick each course? Used to decide how many offerings each course needs."""
    demand = {code: 0 for code in courses_by_code}
    for reg_no, _, _, programme, year in students:
        max_level = min(4, SEMESTERS_DONE[year] // 2 + 1)
        target = rng.randint(scale.min_target_credits, scale.max_target_credits)
        passed = completed[reg_no]
        codes, cum = pools[(programme, max_level, "register")]
        credits, taken = 0, set()
        for code in rng.choices(codes, cum_weights=cum, k=CANDIDATE_DRAWS):
            course = courses_by_code[code]
            if code in taken or code in passed or not all(p in passed for p in course.prereqs):
                continue
            if credits + course.credits > target:
                continue
            taken.add(code)
            credits += course.credits
            demand[code] += 1
            if credits >= target:
                break
    return demand


def make_registrations(rng, students, courses_by_code, offerings, slot_cells, completed,
                       pools, scale: Scale):
    """First come, first served: students register in order of their start time."""
    seats = {o[0]: o[6] for o in offerings}                  # offering_id -> seats left
    offerings_of = {}
    for o in offerings:
        offerings_of.setdefault(o[1], []).append(o)

    # A rush at opening time: start times follow an exponential curve (mean 6 h).
    starts = []
    for student in students:
        offset = rng.expovariate(1 / (6 * 3600))
        if offset > WINDOW_HOURS * 3600:
            offset = rng.uniform(0, WINDOW_HOURS * 3600)
        starts.append((offset, student))
    starts.sort(key=lambda pair: (pair[0], pair[1][0]))

    rows, targets = [], {}
    for offset, (reg_no, _, _, programme, year) in starts:
        done = SEMESTERS_DONE[year]
        max_level = min(4, done // 2 + 1)
        target = rng.randint(scale.min_target_credits, scale.max_target_credits)
        targets[reg_no] = target
        clock = WINDOW_START + timedelta(seconds=offset)
        passed = completed[reg_no]
        codes, cum = pools[(programme, max_level, "register")]

        credits, occupied, taken = 0, set(), set()
        for code in rng.choices(codes, cum_weights=cum, k=CANDIDATE_DRAWS):
            course = courses_by_code[code]
            if code in taken or code in passed:
                continue                                      # DUPLICATE (or already passed)
            if not all(p in passed for p in course.prereqs):
                continue                                      # PREREQ
            if credits + course.credits > min(target, MAX_CREDITS):
                continue                                      # CREDIT_LIMIT
            options = offerings_of[code][:]
            rng.shuffle(options)
            for o in options:
                cells = slot_cells[o[3]]
                if seats[o[0]] > 0 and not (cells & occupied):    # not FULL, no CLASH
                    seats[o[0]] -= 1
                    occupied |= cells
                    taken.add(code)
                    credits += course.credits
                    clock += timedelta(seconds=rng.randint(15, 90))
                    rows.append((o[0], reg_no, clock))
                    break
            if credits >= target:
                break
    return rows, targets


# --------------------------------------------------------------------------- main entry

def generate(slot_cells: dict, slot_kind: dict, scale: Scale = Scale()) -> Dataset:
    """Build the whole dataset.

    slot_cells: slot_id -> frozenset of (day, period), read from slot_timing so
    the database stays the single source of truth for the timetable.
    slot_kind:  slot_id -> 'THEORY' or 'LAB'.
    """
    rng = random.Random(SEED)
    fake = Faker("en_IN")
    fake.seed_instance(SEED)

    courses = make_courses(rng)
    courses_by_code = {c.code: c for c in courses}
    pools = build_pools(courses)

    faculty = make_faculty(rng, fake, scale, courses)
    students = make_students(rng, fake, scale)
    completed, completed_rows = make_completed(rng, students, courses_by_code, pools)
    demand = estimate_demand(rng, students, courses_by_code, completed, pools, scale)
    offerings = make_offerings(rng, courses, faculty, slot_cells, slot_kind, demand, scale)
    registrations, targets = make_registrations(rng, students, courses_by_code, offerings,
                                                slot_cells, completed, pools, scale)

    phones = []
    for reg_no, *_ in students:
        phones.extend(make_phones(rng, reg_no))

    return Dataset(
        students=[(r, f, l, p, y, f"{clean(f)}.{clean(l)}.{r.lower()}@vitstudent.ac.in")
                  for r, f, l, p, y in students],
        phones=phones,
        faculty=[(fid, f, l, DEPARTMENTS[d][0], f"{clean(f)}.{clean(l)}.{fid}@vit.ac.in")
                 for fid, f, l, d in faculty],
        courses=[(c.code, c.title, c.credits, c.ctype) for c in courses],
        theory=[(c.code, min(c.credits, 3), c.credits - min(c.credits, 3))
                for c in courses if c.ctype == "THEORY"],
        labs=[(c.code, 2 * c.credits, LAB_ROOM_TYPE[c.dept]) for c in courses if c.ctype == "LAB"],
        projects=[(c.code, rng.randint(1, 4), rng.choice(DELIVERABLES))
                  for c in courses if c.ctype == "PROJECT"],
        prerequisites=[(c.code, p) for c in courses for p in c.prereqs],
        completed=completed_rows,
        offerings=offerings,
        registrations=registrations,
        target_credits=targets,
    )
