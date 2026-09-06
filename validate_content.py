"""Check every content pack before it goes near the database.

    python validate_content.py

Exits non-zero and prints every problem it finds. Run this after you add or
edit a lesson in content/*.json.
"""
import json
import sys
from pathlib import Path

CONTENT = Path(__file__).parent / "content"
TYPES = {"mc", "tf", "numeric", "text"}
SUBJECTS = {"Maths", "Science", "Practical"}

problems = []
slugs = {}
lessons = questions = 0


def fail(where, message):
    problems.append(f"{where}: {message}")


for path in sorted(CONTENT.glob("*.json")):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(path.name, f"not valid JSON — {exc}")
        continue

    if data.get("subject") not in SUBJECTS:
        fail(path.name, f"subject must be one of {sorted(SUBJECTS)}")
    if not data.get("pack"):
        fail(path.name, "missing 'pack'")

    for lesson in data.get("lessons", []):
        lessons += 1
        slug = lesson.get("slug", "?")
        where = f"{path.name} [{slug}]"

        if slug in slugs:
            fail(where, f"duplicate slug, already used in {slugs[slug]}")
        slugs[slug] = path.name

        kind = lesson.get("kind", "lesson")
        if kind not in ("lesson", "boss"):
            fail(where, f"unknown kind {kind!r}")

        for field in ("title", "strand", "year_level", "intro", "sections", "questions"):
            if not lesson.get(field):
                fail(where, f"missing '{field}'")
        if lesson.get("year_level") not in (4, 6):
            fail(where, "year_level must be 4 or 6")

        if kind == "boss":
            if not lesson.get("covers"):
                fail(where, "a boss needs a 'covers' list of the strands it unlocks from")
            if len(lesson.get("questions", [])) != 14:
                fail(where, f"a boss needs 14 questions, found {len(lesson.get('questions', []))}")
            if any(q.get("difficulty") not in (3, 4) for q in lesson.get("questions", [])):
                fail(where, "every boss question must be difficulty 3 or 4")
        else:
            if not lesson.get("try_this"):
                fail(where, "missing 'try_this'")

            # ---- the hands-on activity ----
            activity = lesson.get("activity")
            if not activity:
                fail(where, "missing 'activity' — every lesson needs one")
            else:
                for field in ("title", "why", "materials", "steps", "record", "check"):
                    if not activity.get(field):
                        fail(where, f"activity is missing '{field}'")
                if activity.get("adult_help") not in ("none", "nearby", "required"):
                    fail(where, "activity adult_help must be none, nearby or required")
                if not 20 <= int(activity.get("xp", 0)) <= 80:
                    fail(where, "activity xp should be between 20 and 80")

                fields = activity.get("record", [])
                if not 2 <= len(fields) <= 6:
                    fail(where, f"activity has {len(fields)} record fields, expected 3-5")
                seen = set()
                types = set()
                for f in fields:
                    fid = f.get("id")
                    if not fid or not f.get("label"):
                        fail(where, "a record field is missing id or label")
                    if fid in seen:
                        fail(where, f"duplicate record field id {fid!r}")
                    seen.add(fid)
                    ftype = f.get("type", "text")
                    types.add(ftype)
                    if ftype == "number" and (f.get("min") is None or f.get("max") is None):
                        fail(where, f"number field {fid!r} needs a min and a max")
                    if ftype == "number" and f.get("min") is not None and f.get("max") is not None \
                            and float(f["min"]) >= float(f["max"]):
                        fail(where, f"number field {fid!r} has min >= max")
                    if ftype == "choice" and len(f.get("options", [])) < 2:
                        fail(where, f"choice field {fid!r} needs at least 2 options")
                    if ftype == "text" and not f.get("min_words"):
                        fail(where, f"text field {fid!r} needs min_words")
                if "number" not in types:
                    fail(where, "activity needs at least one number they measured")
                if "text" not in types:
                    fail(where, "activity needs at least one written answer")

        for section in lesson.get("sections", []):
            if not section.get("heading") or not section.get("body"):
                fail(where, "a section is missing heading or body")
            example = section.get("example")
            if example and ("prompt" not in example or "answer" not in example):
                fail(where, "an example is missing prompt or answer")

        qs = lesson.get("questions", [])
        if kind == "lesson" and len(qs) != 12:
            fail(where, f"expected 12 questions (8 core + 4 challenge), found {len(qs)}")
        if kind == "lesson" and sum(1 for q in qs if q.get("difficulty") == 4) != 4:
            fail(where, "expected exactly 4 challenge questions at difficulty 4")
        for i, q in enumerate(qs, start=1):
            questions += 1
            spot = f"{where} q{i}"
            qtype = q.get("type")
            if qtype not in TYPES:
                fail(spot, f"unknown type {qtype!r}")
                continue
            if not q.get("prompt"):
                fail(spot, "missing prompt")
            if not q.get("explain"):
                fail(spot, "missing explain")
            if q.get("difficulty") not in (1, 2, 3, 4):
                fail(spot, "difficulty must be 1, 2, 3 or 4")

            answer = q.get("answer")
            if qtype == "mc":
                choices = q.get("choices") or []
                if len(choices) < 3:
                    fail(spot, "needs at least 3 choices")
                if len(set(choices)) != len(choices):
                    fail(spot, "duplicate choices")
                if answer not in choices:
                    fail(spot, f"answer {answer!r} is not one of the choices")
            elif qtype == "tf":
                if not isinstance(answer, bool):
                    fail(spot, "answer must be true or false")
            elif qtype == "numeric":
                if not isinstance(answer, (int, float)) or isinstance(answer, bool):
                    fail(spot, "answer must be a number")
            elif qtype == "text":
                if not isinstance(answer, list) or not answer:
                    fail(spot, "answer must be a non-empty list of accepted strings")

print(f"{len(list(CONTENT.glob('*.json')))} packs, {lessons} lessons, {questions} questions")
if problems:
    print(f"\n{len(problems)} problem(s):")
    for p in problems:
        print("  -", p)
    sys.exit(1)
print("All good.")
