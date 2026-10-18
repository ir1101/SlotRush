"""The relational helpers used for the lossless-join checks, and the 4NF/5NF examples."""
from slotrush.normalise import (FDS, Relation, closure, fd_holds, fifth_normal_form,
                                fourth_normal_form, natural_join, project, same_relation)


def test_project_removes_duplicates():
    r = Relation(["a", "b"], [(1, "x"), (2, "x")])
    assert project(r, ["b"]).rows == {("x",)}


def test_natural_join_on_shared_attribute():
    left = Relation(["a", "b"], [(1, "x"), (2, "y")])
    right = Relation(["b", "c"], [("x", 10), ("x", 11), ("z", 12)])
    joined = natural_join(left, right)
    assert joined.attrs == ["a", "b", "c"]
    assert joined.rows == {(1, "x", 10), (1, "x", 11)}


def test_same_relation_ignores_column_order():
    a = Relation(["a", "b"], [(1, 2)])
    b = Relation(["b", "a"], [(2, 1)])
    assert same_relation(a, b)


def test_closure_of_key_is_everything():
    everything = {a for lhs, rhs in FDS for a in lhs + rhs}
    assert closure(["reg_no", "offering_id"], FDS) == everything
    assert "offering_id" not in closure(["reg_no"], FDS)


def test_fd_holds_and_fails():
    r = Relation(["k", "v"], [(1, "a"), (1, "a"), (2, "b")])
    assert fd_holds(r, ["k"], ["v"])
    r.rows.add((1, "c"))
    assert not fd_holds(r, ["k"], ["v"])


def test_4nf_and_5nf_examples_behave_as_documented():
    report = []
    assert fourth_normal_form(report)
    assert fifth_normal_form(report)
    assert sum("[LOSSY]" in line for line in report) == 3
