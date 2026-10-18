# Taste-skill notes: SlotRush home page redesign

Reading of the request: the user chose "Full taste-skill redesign" over keeping the Dragonfly
reference. The home page gets the full run; the app screens (student, catalogue, faculty, admin,
evidence, log in) are restyled to the same tokens and house rules but keep their tables and forms.

## What is real
- Subject: SlotRush, an FFCS-style course registration system built for BCSE302L Database Systems.
- Audience: the examiner and classmates at the project review; then anyone opening the app.
- The one thing to do: log in as a student and try to take a seat (register).
- Stack: Flask + Jinja templates + plain CSS/JS, PostgreSQL behind it.
- Brand: none fixed. Previous look (Dragonfly reference) is being replaced.
- Imagery that exists: our own charts in results/ (raster, real data), the app's own interface
  (timetable grid, catalogue rows: product-ui). No photographs of our own.
  Open collections: punch-card registration, queues, timetable boards, VIT campus.

## Inventory (things only this subject has)
1. The name: Slot (a timetable slot such as T05) + Rush (the minutes after registration opens).
2. FFCS: every student picks a course, a faculty member and a slot.
3. The week: 5 days x 8 periods, 40 cells. T01-T08 meet Mon/Wed/Fri, T09-T16 Tue/Thu,
   20 lab slots are two-period blocks L01-L20.
4. The rooms: SJT, TT, MB, PRP, SMV, GDN building codes in every venue name.
5. The numbers: 30,000 students, 600 courses, 4,500 offerings, 315,596 seats,
   258,514 registrations (82%), 1,547 offerings full, 16 to 27 credits.
6. The moment: registration opens 6 July 2026 at 09:00 IST and stays open 48 hours;
   the first hour carries about 15% of every registration.
7. The constraint: seats_left between 0 and capacity, and one row lock per offering,
   so everyone wanting one class queues on one row.
8. The race: 80 students, 30 seats. Naive code lets 80 in (seats_left ends at 29);
   FOR UPDATE admits exactly 30 and waitlists 50; SERIALIZABLE admits 30 after ~1,300 retries.
9. The receipt: register() answers OK, FULL, CLASH, CREDIT_LIMIT, PREREQ or DUPLICATE.
10. The crash: docker kill in the middle of 1,000 registrations, 0 acknowledged commits lost
    (56 lost when synchronous_commit is off).
11. The course code: BCSE302L.

## Argument (claim -> proof)
1. Thirty seats, eighty students: this is what registration day is.  -> hero statement, one action
2. The database decides who gets each seat, and how matters.         -> the live race (pick a guard,
                                                                         watch 80 try for 30), real numbers
3. It holds at full size.                                            -> 258,514 registrations, 0 clashes,
                                                                         0 over-booked, the profile chart
4. Each person sees only their own part.                             -> student / faculty / admin, links in
5. It keeps its promise through a crash.                             -> docker kill chart, 0 lost
6. Every claim has evidence.                                         -> evidence gallery, link to all of it
7. Try it yourself.                                                  -> log in as a student

## Direction choice
Dealt: type-only-statement, one-motif. Chosen: type-only-statement. Reason: we have no photographs
of the thing; the drama of this subject is in two numbers (30 seats, 80 students) and in what the
database answers, so a first screen of words alone carries it, and our real charts arrive later as
the pictures.

## Idea
On this page, **the 80-students-for-30-seats race from the concurrency demos** becomes
**the type-only first screen and the page's one live thing (a 30-seat grid the visitor watches fill
under the guard they pick)**.
Competitor test: another registration portal has no lost-update experiment; the sentence fails for it.

## Copy deck
Hero bar: wordmark "SlotRush"; action "Try for a seat".
Hero headline (caps, 2 lines, 19 chars): 30 SEATS / 80 STUDENTS
Supporting: SlotRush is FFCS-style course registration for BCSE302L, where PostgreSQL decides who
gets each seat when everyone asks at once.

Showcase heading: Who got a seat
Paragraph: Eighty bots asked one 30-seat class for a place in the same instant. Without a lock, each
read seats_left, paused 50 ms and wrote back its stale value minus one. With SELECT … FOR UPDATE they
queued on the row. Pick a guard and see what the database admitted.
Guards: No lock / Row lock / Serializable. Left specimen 30 "Seats in the class"; right specimen
admitted count (80 / 30 / 30) with its outcome line from results/demo_*.json.

Photo band: the 1972 queue. Caption: Students queuing for rooms in Helsinki, 1972. On registration
day the queue is still there; now it forms on one row of the offering table.

Stats heading: Every seat accounted for
Note: check-data ran eight rules over the loaded data and found no clash, no course taken twice and
no class over its capacity.
Total: 258,514. Caption: registrations in FALL2026, filling 82% of 315,596 seats.
Slip: registrations per department under "Engineering schools" and "Sciences and humanities",
closing on the total.

Poster list: Student (Timetable, credits, drop and swap) / Catalogue (Search the offerings, register)
/ Faculty (Class lists through row-level security) / Seats (Fill of all 4,500 offerings) /
Evidence (Every chart, plan and log).

Wall: Evidence / 80 in 30 seats with no lock / registration gauge photo / 40P01 deadlock detected /
0 commits lost to docker kill / 40 lost with async commit / lecture theatre photo / 60x faster with an
index / card storage photo / 5NF three-way join, lossless / 111 tests passing / VIT hostels photo.

Close: Be one of / the thirty. Sentence: Log in as any of the 30,000 students and ask register() for
a seat; it answers OK, FULL or CLASH in milliseconds. Button: Try for a seat.
Footer columns: Pages, Run it, Project, Pictures (credits). Wordmark SLOTRUSH. Legal line.

Size adjustments: five steps (small, body, head, display, mega). The receipt total uses display
(9vw) instead of 18vw because "258,514" is seven characters and must fit half the width.

## Gate and critique log
- Before: lint 26 FAIL / 11 WARN on the Dragonfly build (monospace labels, 01/02 numbering, hairlines).
- inspect.mjs runs on this machine with `node --experimental-websocket` (Node 20.17).
- Inspect round 1: 3 FAIL (eyebrow captions, covered headline from the two-copy waterline,
  768px overflow from a transform-centred sentence) + 12 font sizes. Also a class clash (.bar).
- Round 2: covered-text fixed by drawing the bone half as h1::after; sizes cut to five
  (14 / 19 / 42 / 130 / 432 px); captions removed; queries panel removed from home.
- Round 3: 0 FAIL. WARN monospace (real code only) and no footage (no honest short clip;
  photo drift instead) are defended.
- Critique round 1: 7.2 (reveals not firing in tall captures). Round 2: design 7.5, usability 8,
  creativity 8, content 8.5, overall 7.9. Remaining: empty olive band in the receipt (blueprint).

## Live thing
"Pick a guard": three choices (no lock, row lock, serializable). The 30-seat grid fills with 80
students using the measured outcome from results/demo_*.json: no lock overfills to 80 in 30 seats,
row lock fills 30 and lists 50 on the waitlist, serializable fills 30 and counts the retries.
Fallback without script: the three outcomes as plain sentences.
