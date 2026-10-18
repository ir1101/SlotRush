# NoSQL and the CAP theorem (draft)

Evidence: `python -m slotrush reviews` writes
- `results/nosql_index_explain.txt`: the same query before and after adding an index
- `results/nosql_aggregations.txt` / `.json`: four aggregation pipelines and their output
- `results/nosql_reviews.png`: most common tags and average rating by course type

## 1. Why course reviews suit a document store

A review is written once, read many times, and almost never joined with anything. Its shape
depends on the course type:

```json
{ "reg_no": "23BCE0042", "offering_id": 1207, "semester": "FALL2026",
  "course":  { "code": "BCSE302L", "title": "Database Systems", "type": "THEORY" },
  "faculty": { "id": 1031, "name": "A. Kumar" },
  "rating": 4, "tags": ["clear lectures", "good notes"],
  "comment": "Concepts were explained clearly. The notes are enough to prepare for exams.",
  "created_at": "2026-09-14T10:21:00Z",
  "lecture": { "clarity": 4, "pace": "right", "exam_difficulty": 3 } }
```

A lab review has `"lab": {"equipment", "instructor_help", "experiments_done"}` instead of
`lecture`, and a project review has
`"project": {"team_size", "guide_availability", "domain", "milestones": [ {"name", "on_time"}, … ]}`,
an array of embedded documents.

| Need | Relational | Document store |
|---|---|---|
| Different fields per review type | one wide table full of NULLs, or a supertype table plus three subtype tables (like `course`) | each document just has the fields it needs |
| Tags (a list) | separate `review_tag` table, joined on every read | an array inside the document; `$unwind` when aggregating |
| Milestones (list of small records) | another table | array of embedded documents |
| Show a review with course and faculty names | joins to `course` and `faculty` | names copied into the document (denormalised on purpose: they rarely change, and a stale name in an old review is harmless) |
| Adding a new question to next semester's form | `ALTER TABLE` | new documents simply carry the new field; old ones do not |

What reviews give up, and why that is acceptable: no foreign keys (a review can point to an
offering that no longer exists), no multi-document ACID transaction by default, and duplicated
names. None of these can over-book a seat.

In the aggregation `rating_by_course_type`, `$avg: "$lecture.clarity"` is computed only over
documents that have that field, so one pipeline averages three different type-specific fields
in one pass. That is the flexible schema doing useful work.

The index evidence (`nosql_index_explain.txt`): `find({"faculty.id": …, "rating": {"$gte": 4}})`
went from **COLLSCAN, 5,000 documents examined** to **IXSCAN on
`{faculty.id: 1, rating: -1}`, 25 keys and 25 documents examined**, the same idea as a B-tree
index in PostgreSQL. MongoDB's indexes are B-trees too.

## 2. CAP for SlotRush

**CAP theorem** (Brewer; proved by Gilbert and Lynch): when a network **P**artition splits the
replicas of a distributed data store, it must choose between
- **C**onsistency: every read sees the latest write (all replicas agree), and
- **A**vailability: every request to a working node gets a non-error answer.

You cannot have both *during* a partition. When there is no partition you can have both, so the
real question is: **what should each kind of data do when the network fails?**

### Seat allotment: choose C (CP)

- The invariant is hard: `seats_left` never goes below 0, and registrations never exceed capacity.
  The lost-update demo shows what breaks when two writers act on stale reads: 80 students in a
  30-seat class.
- If two partitions both accepted registrations for the same offering, each could give away the
  last seat, and they could not be merged afterwards without telling some students
  "you are no longer registered". That is worse than "try again in a minute".
- So during a partition the side that cannot reach the primary must **refuse** registrations
  (lose A). In this project that is PostgreSQL with a single primary: every `register()` takes a
  row lock on the one authoritative copy of the offering. A replicated deployment would use
  synchronous replication (commit only after a standby confirms) so a failover cannot lose an
  acknowledged registration. The crash demo shows the single-node version of the same promise.

### Reviews: choose A (AP), accept eventual consistency

- No invariant links reviews to each other. Two students' reviews never conflict.
- If a review written on one side of a partition shows up on the other side a few seconds or
  minutes later, nobody is harmed. Average ratings are statistics; being slightly out of date
  is fine.
- So reviews should stay writable and readable during a partition: MongoDB with a replica set,
  writes with a modest write concern (`w: 1`), reads allowed from secondaries
  (`readPreference: secondaryPreferred`). Each replica converges once the partition heals:
  **eventual consistency**.
- Caveat for the viva: MongoDB itself is usually called CP (a minority partition cannot elect a
  primary, so it cannot accept writes). The AP behaviour above comes from how the reviews
  workload is configured (secondary reads, low write concern), not from MongoDB being AP by
  nature.

### PACELC: the trade-off when there is no partition

PACELC (Abadi) adds: **E**lse, when there is no partition, choose between **L**atency and
**C**onsistency.
- Seats: PC/EC. Pay the latency of locks (the locking demo queues 80 bots one at a time) or of
  serialization retries, to stay consistent.
- Reviews: PA/EL. Answer from the nearest replica, fast, even if it is a few writes behind.

### Summary

| Data | Invariant | Partition behaviour | Store and settings |
|---|---|---|---|
| Offerings, registrations, waitlist | seats_left ∈ [0, capacity], no clashes, credit limit | refuse writes on the minority side (CP) | PostgreSQL, row locks, `synchronous_commit = on` |
| Reviews | none between documents | keep accepting reads and writes, converge later (AP) | MongoDB, `w: 1`, `secondaryPreferred` reads |

Using two stores, each matched to the guarantees its data needs, is called **polyglot
persistence**.
