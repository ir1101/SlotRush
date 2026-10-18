# Normalisation (draft)

Evidence: `python -m slotrush normalise` writes
- `results/flat_registration_export.csv`: the flat table (registrations of the first 500 students
  by reg_no, 4,247 rows; a sample keeps the file small)
- `results/normalisation_lossless_check.txt`: FD checks, closures, every lossless-join test
- `results/nf4_faculty_preference.csv`, `results/nf5_eligibility.csv`: the 4NF and 5NF examples

The script ([`slotrush/normalise.py`](../slotrush/normalise.py)) treats each relation as a Python
set of tuples. "Lossless" is tested literally: project the parts, natural-join them back, and
compare the result with the original as sets.

## 1. The flat relation

```
RegistrationFlat(reg_no, first_name, last_name, programme, phones,
                 offering_id, semester, course_code, title, credits, course_type,
                 faculty_id, faculty_name, school, slot_id, venue, capacity, registered_at)
```

One row per registration. `phones` holds every phone number of the student in one field,
separated by `;` (for example `+919812345678;+917012345678`).

**It is not in 1NF**: `phones` is not atomic (it is a multivalued attribute packed into one
field). It also repeats every student, course and faculty detail on every registration.

## 2. First normal form

Two standard ways to make `phones` atomic:

- *(a) One row per phone.* Gives `R1NF` with `phone` instead of `phones`: 5,776 rows instead of
  4,247, because every registration of a two-phone student now appears twice.
- *(b) Move the multivalued attribute out* into `StudentPhone(reg_no, phone)` and drop it from
  the main relation. This is the ER-to-relational mapping rule for a multivalued attribute.

The script builds (a) and then shows that (b) is a lossless decomposition of it:

```
[LOSSLESS] 1NF: move the multivalued phone into StudentPhone
    original 5,776 rows, joined back 5,776 rows, spurious 0
```

From here on, `R` means the relation without phones:
`R(reg_no, first_name, last_name, programme, offering_id, semester, course_code, title, credits,
course_type, faculty_id, faculty_name, school, slot_id, venue, capacity, registered_at)`.

## 3. Functional dependencies

| # | FD | Meaning |
|---|---|---|
| FD1 | reg_no → first_name, last_name, programme | a student has one name and programme |
| FD2 | course_code → title, credits, course_type | a course has one title, credit value and type |
| FD3 | faculty_id → faculty_name, school | |
| FD4 | offering_id → semester, course_code, faculty_id, slot_id, venue, capacity | an offering is one course, by one faculty member, in one slot |
| FD5 | reg_no, offering_id → registered_at | one registration time per student per offering |

All five were checked against the exported data (no two rows agree on the left side but differ
on the right): **all hold**. `reg_no, offering_id → phone` does **not** hold, which is the 1NF
problem above. (Also true, but left out because it only holds when venue is not NULL:
venue, semester, slot_id → offering_id.)

### Attribute closures

Computed with the closure algorithm (repeat: if the left side of an FD is inside X⁺, add its right
side) over FD1 to FD5:

| X | X⁺ | Superkey of R? |
|---|---|---|
| {reg_no} | reg_no, first_name, last_name, programme | no |
| {offering_id} | offering_id, semester, course_code, faculty_id, slot_id, venue, capacity, title, credits, course_type, faculty_name, school | no |
| {reg_no, offering_id} | all 17 attributes of R | **yes** |

Neither reg_no nor offering_id alone is a superkey, so **{reg_no, offering_id} is the candidate
key** of R (minimal superkey). In the 1NF version (a) the key is {reg_no, offering_id, phone}.

Prime attributes: reg_no, offering_id. Every other attribute is non-prime.

## 4. Decomposition, step by step

### 2NF: no non-prime attribute may depend on PART of a key

Partial dependencies in R: FD1 (on reg_no alone) and FD4 with its consequences (on offering_id
alone). Split them off:

- `Student(reg_no, first_name, last_name, programme)` from FD1
- `OfferingWide(offering_id, semester, course_code, title, credits, course_type, faculty_id,
  faculty_name, school, slot_id, venue, capacity)` from offering_id⁺
- `Registration(reg_no, offering_id, registered_at)`: the key with what depends on all of it

```
[LOSSLESS] 2NF: remove partial dependencies on {reg_no, offering_id}
    original 4,247 rows, joined back 4,247 rows, spurious 0
```

### 3NF: no non-prime attribute may depend transitively on a key

`OfferingWide` still has offering_id → course_code → title, credits, course_type and
offering_id → faculty_id → faculty_name, school. Split them off:

- `Course(course_code, title, credits, course_type)`
- `Faculty(faculty_id, faculty_name, school)`
- `Offering(offering_id, semester, course_code, faculty_id, slot_id, venue, capacity)`

```
[LOSSLESS] 3NF/BCNF: remove transitive dependencies through course_code and faculty_id
    original 2,494 rows, joined back 2,494 rows, spurious 0
```

### BCNF: every determinant must be a superkey

| Relation | Key | FDs | BCNF? |
|---|---|---|---|
| Student | reg_no | FD1 | yes |
| StudentPhone | (reg_no, phone) | none (all-key) | yes |
| Registration | (reg_no, offering_id) | FD5 | yes |
| Offering | offering_id; also (venue, semester, slot_id) when venue is not NULL | FD4 | yes: both determinants are candidate keys |
| Course | course_code | FD2 | yes |
| Faculty | faculty_id | FD3 | yes |

These six relations are the core of the real schema in `sql/01_schema.sql`. (The real `faculty`
stores the name as first_name and last_name; the export joins them into one column.)

### Lossless-join check

**Theory** (binary decomposition test): splitting R into R1 and R2 is lossless if
R1 ∩ R2 → R1 or R1 ∩ R2 → R2, i.e. the shared attributes are a key of one side. Every split
above shares a key: reg_no (key of Student), offering_id (key of OfferingWide/Offering),
course_code (key of Course), faculty_id (key of Faculty).

**Data**: joining all six relations back gives exactly the 1NF relation:

```
[LOSSLESS] All six BCNF relations joined back = the 1NF relation
    original 5,776 rows, joined back 5,776 rows, spurious 0
```

**Contrast, a lossy split**: (reg_no, slot_id) and (slot_id, offering_id, course_code) share only
slot_id, which is a key of neither part. Joining back gives 312,677 rows instead of 4,247:
308,430 spurious tuples, every student paired with every class in each slot they use.

### Dependency preservation

Each FD's attributes all fit inside one final relation (FD1 in Student, FD2 in Course, FD3 in
Faculty, FD4 in Offering, FD5 in Registration), so every FD can be checked on one table without
a join. The decomposition is dependency-preserving.

## 5. Fourth normal form example

`FacultyPreference(faculty_id, expertise, preferred_slot)`: each faculty member lists areas of
expertise and preferred teaching slots. The two lists are **independent** of each other.

| faculty_id | expertise | preferred_slot |
|---|---|---|
| 1002 | Machine Learning | T03 |
| 1002 | Machine Learning | T04 |
| 1002 | Machine Learning | T12 |
| 1002 | Machine Learning | T13 |
| 1002 | Statistics | T03 |
| … | … | … (3 × 4 = 12 rows for faculty 1002) |

- No non-trivial FD holds, the only key is all three attributes, so it **is in BCNF**.
- Two multivalued dependencies hold: **faculty_id →→ expertise** and
  **faculty_id →→ preferred_slot**. Every faculty member's rows are the full cross product of
  their two lists (31 rows in the example).
- Anomaly: adding one expertise for faculty 1002 needs 4 new rows (one per preferred slot);
  forgetting one leaves a row set that wrongly suggests the two facts are related.
- 4NF decomposition: `FacultyExpertise(faculty_id, expertise)` and
  `FacultySlotPreference(faculty_id, preferred_slot)`. Lossless (an MVD X →→ Y holds exactly when
  splitting into XY and XZ is lossless), and 22 rows instead of 31.

```
[LOSSLESS] 4NF split on the MVD
    original 31 rows, joined back 31 rows, spurious 0
```

## 6. Fifth normal form example

`Eligibility(faculty, course, slot)` with the business rule: *if faculty f can teach course c,
course c may run in slot s, and f is available in slot s, then f may teach c in s.* That rule is
the **join dependency** \*(FC, CS, FS): the relation always equals the join of its three
two-column projections. (Data adapted from the Elmasri–Navathe SUPPLY example, names changed.)

| faculty | course | slot |
|---|---|---|
| Rao | BCSE302L | T01 |
| Rao | BCSE303L | T02 |
| Iyer | BCSE302L | T02 |
| Menon | BCSE303L | T03 |
| Iyer | BMAT201L | T01 |
| Iyer | BCSE302L | T01 |
| Rao | BCSE302L | T02 |

- All-key, no FDs: BCNF.
- Every **two**-way split is lossy (2 spurious tuples each), so no MVD holds: 4NF.
  For example (faculty, course) ⋈ (course, slot) invents (Rao, BCSE303L, T03).
- The **three**-way split is lossless (7 rows back, 0 spurious): the JD holds, and it is not
  implied by a key, so the relation is **not in 5NF**. 5NF decomposition:
  `CanTeach(faculty, course)`, `CourseSlot(course, slot)`, `Available(faculty, slot)`.

```
[LOSSY]    two projections: (faculty, course) + (course, slot)    joined back 9 rows, spurious 2
[LOSSY]    two projections: (faculty, course) + (faculty, slot)   joined back 9 rows, spurious 2
[LOSSY]    two projections: (course, slot) + (faculty, slot)      joined back 9 rows, spurious 2
[LOSSLESS] three projections: join dependency *(FC, CS, FS)       joined back 7 rows, spurious 0
```
