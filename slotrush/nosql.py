"""The 'reviews' command: course reviews in MongoDB.

Reviews are documents whose shape depends on the course type:
  THEORY  reviews carry a "lecture" sub-document (clarity, pace, exam difficulty)
  LAB     reviews carry a "lab" sub-document (equipment, instructor help, experiments)
  PROJECT reviews carry a "project" sub-document with an array of milestones
A relational table would need either many NULL columns or three extra tables;
a document store keeps each review as one self-contained document.

Steps: (re)seed 5,000 reviews of real registrations from PostgreSQL, explain
a query before and after adding an index, run four aggregation pipelines.
Output: results/nosql_index_explain.txt, results/nosql_aggregations.txt and
.json, results/nosql_reviews.png.
"""
import json
import random
from datetime import datetime, timedelta, timezone

from . import charts
from .config import RESULTS_DIR, SEED, SEMESTER
from .db import mongo_client, pg_connect

# Reviews per course type, sampled separately: project registrations are rare
# (about 220 of 258,000), so a plain random sample would contain almost none.
REVIEWS = {"THEORY": 2_800, "LAB": 2_000, "PROJECT": 200}
DATABASE = "slotrush"

# (positive tags, negative tags) per course type
TAGS = {
    "THEORY": (["clear lectures", "lenient grading", "engaging", "good notes"],
               ["tough exams", "heavy workload", "fast paced", "boring"]),
    "LAB": (["well equipped", "helpful TA", "fair viva"],
            ["outdated equipment", "long experiments", "crowded"]),
    "PROJECT": (["approachable guide", "flexible deadlines", "real-world problem", "great team"],
                ["unclear expectations"]),
}
PHRASES = {
    "clear lectures": "Concepts were explained clearly.",
    "tough exams": "The exams were much harder than the lectures.",
    "lenient grading": "Grading was fair and lenient.",
    "heavy workload": "Too many assignments every week.",
    "engaging": "Classes were interactive.",
    "fast paced": "The syllabus was covered very fast.",
    "good notes": "The notes are enough to prepare for exams.",
    "boring": "Hard to stay awake in class.",
    "well equipped": "Every bench had working equipment.",
    "helpful TA": "The lab assistant helped whenever we were stuck.",
    "outdated equipment": "Half the kits did not work.",
    "long experiments": "Experiments rarely finished in two periods.",
    "fair viva": "The viva questions were fair.",
    "crowded": "Three people shared one setup.",
    "approachable guide": "The guide was easy to reach.",
    "flexible deadlines": "Reviews could be rescheduled.",
    "real-world problem": "We worked on an actual industry problem.",
    "unclear expectations": "Nobody told us what the final deliverable was.",
    "great team": "My team was excellent.",
}
DOMAINS = ["Machine Learning", "IoT", "Web", "Embedded", "Energy", "Structures", "Data Analytics"]

PIPELINES = {
    "average_rating_per_faculty": [
        {"$group": {"_id": "$faculty.id", "name": {"$first": "$faculty.name"},
                    "avg_rating": {"$avg": "$rating"}, "reviews": {"$sum": 1}}},
        {"$match": {"reviews": {"$gte": 5}}},
        {"$sort": {"avg_rating": -1, "reviews": -1, "_id": 1}},
        {"$limit": 10},
    ],
    "most_common_tags": [
        {"$unwind": "$tags"},                              # one document per tag
        {"$group": {"_id": "$tags", "count": {"$sum": 1}}},
        {"$sort": {"count": -1, "_id": 1}},
        {"$limit": 10},
    ],
    "rating_by_course_type": [
        # $avg ignores missing fields, so each type-specific average only uses
        # the documents that HAVE that field: the flexible schema at work.
        {"$group": {"_id": "$course.type",
                    "avg_rating": {"$avg": "$rating"},
                    "reviews": {"$sum": 1},
                    "avg_lecture_clarity": {"$avg": "$lecture.clarity"},
                    "avg_lab_equipment": {"$avg": "$lab.equipment"},
                    "avg_guide_availability": {"$avg": "$project.guide_availability"}}},
        {"$sort": {"_id": 1}},
    ],
    "labs_with_worst_equipment": [
        {"$match": {"course.type": "LAB"}},
        {"$group": {"_id": "$course.code", "title": {"$first": "$course.title"},
                    "avg_equipment": {"$avg": "$lab.equipment"}, "reviews": {"$sum": 1}}},
        {"$match": {"reviews": {"$gte": 3}}},
        {"$sort": {"avg_equipment": 1, "_id": 1}},
        {"$limit": 5},
    ],
}


def clamp(x: float) -> int:
    return max(1, min(5, round(x)))


def make_review(rng: random.Random, reg: dict, faculty_quality: float) -> dict:
    """One review document. Fields common to all types first, then the
    type-specific sub-document."""
    ctype = reg["course_type"]
    rating = clamp(rng.gauss(faculty_quality, 0.8))
    # The higher the rating, the more likely each tag is a positive one.
    positive, negative = TAGS[ctype]
    tags = sorted({rng.choice(positive if rng.random() < (rating - 1) / 4 else negative)
                   for _ in range(rng.randint(1, 3))})
    doc = {
        "reg_no": reg["reg_no"],
        "offering_id": reg["offering_id"],
        "semester": SEMESTER,
        "course": {"code": reg["course_code"], "title": reg["title"], "type": ctype},
        "faculty": {"id": reg["faculty_id"], "name": reg["faculty_name"]},
        "rating": rating,
        "tags": tags,
        "comment": " ".join(PHRASES[t] for t in tags),
        "created_at": datetime(2026, 9, 1, tzinfo=timezone.utc)
                      + timedelta(minutes=rng.randrange(60 * 24 * 45)),
    }
    if ctype == "THEORY":
        doc["lecture"] = {"clarity": clamp(rating + rng.gauss(0, 0.7)),
                          "pace": rng.choice(["slow", "right", "fast"]),
                          "exam_difficulty": rng.randint(1, 5)}
    elif ctype == "LAB":
        doc["lab"] = {"equipment": clamp(rng.gauss(3.4, 1.0)),
                      "instructor_help": clamp(rating + rng.gauss(0, 0.7)),
                      "experiments_done": rng.randint(6, 12)}
    else:
        doc["project"] = {"team_size": rng.randint(1, 4),
                          "guide_availability": clamp(rating + rng.gauss(0, 0.6)),
                          "domain": rng.choice(DOMAINS),
                          "milestones": [{"name": name, "on_time": rng.random() < 0.7}
                                         for name in ("proposal", "review 1", "review 2", "final")]}
    return doc


def registrations_to_review(rng: random.Random) -> list[dict]:
    """A seeded random sample of real registrations, with the names reviews need."""
    with pg_connect() as conn:
        cur = conn.execute("""
            SELECT r.reg_no, r.offering_id, c.course_code, c.title, c.course_type,
                   f.faculty_id, f.first_name || ' ' || f.last_name AS faculty_name
            FROM registration r
            JOIN offering o ON o.offering_id = r.offering_id
            JOIN course c   ON c.course_code = o.course_code
            JOIN faculty f  ON f.faculty_id = o.faculty_id
            WHERE o.semester = %s
            ORDER BY r.offering_id, r.reg_no""", (SEMESTER,))
        columns = [d.name for d in cur.description]
        rows = [dict(zip(columns, row)) for row in cur.fetchall()]
    sample = []
    for ctype, wanted in REVIEWS.items():
        of_type = [r for r in rows if r["course_type"] == ctype]
        if len(of_type) < wanted:
            raise SystemExit(f"Only {len(of_type)} {ctype} registrations: run "
                             "'python -m slotrush load' first.")
        sample.extend(rng.sample(of_type, wanted))
    return sample


def explain(collection, query: dict) -> dict:
    """executionStats for a find(): which plan, how many documents and keys were read."""
    result = collection.database.command(
        {"explain": {"find": collection.name, "filter": query}, "verbosity": "executionStats"})
    stats = result["executionStats"]
    plan = result["queryPlanner"]["winningPlan"]
    stages = []
    while plan:                                    # e.g. FETCH -> IXSCAN, or COLLSCAN
        stages.append(plan["stage"] + (f"({plan['indexName']})" if "indexName" in plan else ""))
        plan = plan.get("inputStage")
    return {"plan": " -> ".join(stages), "returned": stats["nReturned"],
            "docs_examined": stats["totalDocsExamined"], "keys_examined": stats["totalKeysExamined"],
            "time_ms": stats["executionTimeMillis"]}


def run() -> int:
    rng = random.Random(SEED)
    registrations = registrations_to_review(rng)
    faculty_ids = sorted({r["faculty_id"] for r in registrations})
    quality = {fid: rng.uniform(2.3, 4.7) for fid in faculty_ids}     # some faculty are better
    docs = [make_review(rng, reg, quality[reg["faculty_id"]]) for reg in registrations]

    client = mongo_client()
    try:
        reviews = client[DATABASE]["reviews"]
        reviews.drop()                              # reseed from scratch: reproducible
        reviews.insert_many(docs)
        print(f"Seeded {reviews.count_documents({}):,} reviews into {DATABASE}.reviews")
        for ctype in TAGS:
            sample = reviews.find_one({"course.type": ctype}, {"_id": 0, "comment": 0})
            print(f"  {ctype:<7} review fields: {', '.join(sample)}")

        busiest = max(faculty_ids, key=lambda f: sum(r["faculty_id"] == f for r in registrations))
        query = {"faculty.id": busiest, "rating": {"$gte": 4}}
        before = explain(reviews, query)
        index_name = reviews.create_index([("faculty.id", 1), ("rating", -1)])
        after = explain(reviews, query)
        lines = [f"Query: db.reviews.find({json.dumps(query)})",
                 f"Before index: {before}",
                 f"Index created: {index_name}  (compound: faculty.id ascending, rating descending)",
                 f"After index:  {after}"]
        (RESULTS_DIR / "nosql_index_explain.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("\n" + "\n".join(lines))

        results = {}
        text = []
        for name, pipeline in PIPELINES.items():
            results[name] = list(reviews.aggregate(pipeline))
            text.append(f"== {name}\npipeline: {json.dumps(pipeline)}")
            for doc in results[name]:
                text.append("  " + json.dumps(doc, default=str, ensure_ascii=False))
            text.append("")
    finally:
        client.close()

    (RESULTS_DIR / "nosql_aggregations.txt").write_text("\n".join(text), encoding="utf-8")
    (RESULTS_DIR / "nosql_aggregations.json").write_text(
        json.dumps(results, indent=2, default=str), encoding="utf-8")
    print("\n" + "\n".join(text))
    print("Saved results/nosql_index_explain.txt, results/nosql_aggregations.txt and .json")
    chart(results)
    return 0


def chart(results: dict) -> None:
    fig, (left, right) = charts.figure(ncols=2, width=11, height=4.2)
    tags = list(reversed(results["most_common_tags"]))
    left.barh([t["_id"] for t in tags], [t["count"] for t in tags], height=0.5, color=charts.PRIMARY)
    left.set_title("Most common review tags")
    left.set_xlabel("reviews")
    left.grid(axis="y", visible=False)

    by_type = results["rating_by_course_type"]
    bars = right.bar([t["_id"] for t in by_type], [round(t["avg_rating"], 2) for t in by_type],
                     width=0.5, color=charts.PRIMARY)
    charts.label_bars(right, bars, "{:.2f}")
    right.set_ylim(0, 5)
    right.set_title("Average rating by course type")
    right.set_ylabel("rating (1-5)")
    print(f"Chart: {charts.save(fig, 'nosql_reviews.png')}")
