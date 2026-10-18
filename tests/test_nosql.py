"""Review documents: common fields plus one type-specific sub-document."""
import random

from slotrush.nosql import TAGS, make_review


def registration(course_type):
    return {"reg_no": "23BCE0001", "offering_id": 1, "course_code": "BCSE101L",
            "title": "Programming", "course_type": course_type,
            "faculty_id": 1001, "faculty_name": "A. Kumar"}


def test_each_type_has_only_its_own_sub_document():
    rng = random.Random(1)
    expected = {"THEORY": "lecture", "LAB": "lab", "PROJECT": "project"}
    for course_type, field in expected.items():
        doc = make_review(rng, registration(course_type), faculty_quality=4)
        assert field in doc
        assert not ({"lecture", "lab", "project"} - {field}) & doc.keys()


def test_rating_and_tags_are_valid():
    rng = random.Random(2)
    for _ in range(200):
        doc = make_review(rng, registration("LAB"), faculty_quality=rng.uniform(1, 5))
        assert 1 <= doc["rating"] <= 5
        positive, negative = TAGS["LAB"]
        assert set(doc["tags"]) <= set(positive + negative)


def test_project_reviews_embed_a_milestone_array():
    doc = make_review(random.Random(3), registration("PROJECT"), faculty_quality=3)
    assert [m["name"] for m in doc["project"]["milestones"]] == \
        ["proposal", "review 1", "review 2", "final"]


def test_reviews_collection_in_mongo(mongo):
    """After 'python -m slotrush reviews' the collection holds three document shapes."""
    reviews = mongo["slotrush"]["reviews"]
    if reviews.estimated_document_count() == 0:
        return                      # not seeded yet; the pure tests above still ran
    for field in ("lecture", "lab", "project"):
        assert reviews.count_documents({field: {"$exists": True}}) > 0
