"""Load the JSON content packs in content/ into the database.

Safe to run repeatedly: lessons are matched on `slug` and updated in place,
and a lesson's questions are replaced with the current file version.
Kid profiles, attempts and progress are never touched.

    python seed.py            # load / refresh all packs
    python seed.py --reset    # drop and rebuild every table first (wipes progress)
"""
import json
import sys
from pathlib import Path

from models import Activity, Badge, Kid, Lesson, Question, db

CONTENT_DIR = Path(__file__).parent / "content"

BADGES = [
    ("first_quiz",   "Off the Mark",      "Finished your first quiz",                      "1"),
    ("perfect",      "Clean Sweep",       "Got every question right in a quiz",            "*"),
    ("perfect_five", "Five Clean Sweeps", "Five perfect quizzes",                          "5"),
    ("streak_3",     "Three in a Row",    "Practised three days running",                  "3"),
    ("streak_7",     "Week Strong",       "Practised seven days running",                  "7"),
    ("century",      "Century",           "Answered 100 questions",                        "100"),
    ("five_hundred", "Big Innings",       "Answered 500 questions",                        "500"),
    ("maths_10",     "Number Cruncher",   "Mastered 10 maths lessons",                     "N"),
    ("science_10",   "Lab Coat",          "Mastered 10 science lessons",                   "S"),
    ("practical_10", "Handy",             "Mastered 10 practical lessons",                 "P"),
    ("all_rounder",  "All Rounder",       "Mastered a lesson in all three subjects",       "A"),
    ("stretch_10",   "Stretch Merchant",  "Got 10 stretch questions right",                "^"),
    ("level_5",      "Level 5",           "Reached level 5",                               "L"),
    ("hands_on",     "Hands On",          "Got your first activity signed off",            "H"),
    ("hands_on_10",  "Ten Jobs Done",     "Ten activities signed off",                     "10"),
    ("hands_on_all", "Nothing Skipped",   "Every activity at your year level signed off",  "++"),
    ("challenger",   "Challenger",        "Got 25 challenge questions right",              "C"),
    ("boss_down",    "Boss Down",         "Beat a boss challenge",                         "B"),
    ("boss_all",     "Untouchable",       "Beat every boss at your year level",            "!!"),
]


def seed_badges():
    for code, name, description, icon in BADGES:
        badge = Badge.query.filter_by(code=code).first()
        if badge is None:
            db.session.add(Badge(code=code, name=name, description=description, icon=icon))
        else:
            badge.name, badge.description, badge.icon = name, description, icon
    db.session.commit()


def seed_kids():
    """Create the two default profiles only if there are none at all."""
    if Kid.query.count():
        return
    db.session.add_all([
        Kid(name="Kid One", year_level=4, colour="teal", emoji="4"),
        Kid(name="Kid Two", year_level=6, colour="amber", emoji="6"),
    ])
    db.session.commit()


def load_pack(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    pack = data["pack"]
    subject = data["subject"]
    added = updated = 0

    for item in data["lessons"]:
        lesson = Lesson.query.filter_by(slug=item["slug"]).first()
        if lesson is None:
            lesson = Lesson(slug=item["slug"])
            db.session.add(lesson)
            added += 1
        else:
            updated += 1

        lesson.pack = pack
        lesson.subject = subject
        lesson.kind = item.get("kind", "lesson")
        lesson.covers = item.get("covers", [])
        lesson.strand = item.get("strand", "")
        lesson.year_level = int(item.get("year_level", 4))
        lesson.title = item["title"]
        lesson.curriculum_code = item.get("curriculum_code", "") or ""
        lesson.curriculum_text = item.get("curriculum_text", "") or ""
        lesson.position = int(item.get("position", 0))
        lesson.est_minutes = int(item.get("est_minutes", 12))
        lesson.intro = item.get("intro", "")
        lesson.sections = item.get("sections", [])
        lesson.key_points = item.get("key_points", [])
        lesson.try_this = item.get("try_this", "")

        db.session.flush()

        # Questions are updated in place, matched on their position in the
        # lesson, so their row ids survive. Answer history and in-flight
        # quizzes both point at those ids — deleting and recreating the rows
        # would break them (and Postgres would refuse outright).
        existing = {q.position: q for q in Question.query.filter_by(lesson_id=lesson.id).all()}
        incoming = item.get("questions", [])

        for i, q in enumerate(incoming, start=1):
            row = existing.pop(i, None)
            if row is None:
                row = Question(lesson_id=lesson.id, position=i)
                db.session.add(row)
            row.qtype = q["type"]
            row.prompt = q["prompt"]
            row.choices = q.get("choices", [])
            row.answer = q.get("answer")
            row.tolerance = float(q.get("tolerance", 0.001))
            row.unit = q.get("unit", "") or ""
            row.explanation = q.get("explain", "")
            row.difficulty = int(q.get("difficulty", 2))

        # Anything left over is a question the pack no longer has.
        for row in existing.values():
            db.session.delete(row)          # its answer logs cascade with it

        # The hands-on activity, updated in place so any sign-offs survive.
        spec = item.get("activity")
        if spec:
            activity = Activity.query.filter_by(lesson_id=lesson.id).first()
            if activity is None:
                activity = Activity(lesson_id=lesson.id)
                db.session.add(activity)
            activity.title = spec["title"]
            activity.why = spec.get("why", "")
            activity.est_minutes = int(spec.get("est_minutes", 25))
            activity.adult_help = spec.get("adult_help", "nearby")
            activity.materials = spec.get("materials", [])
            activity.steps = spec.get("steps", [])
            activity.record_fields = spec.get("record", [])
            activity.check_note = spec.get("check", "")
            activity.xp = int(spec.get("xp", 40))

    db.session.commit()
    return added, updated


def run(reset=False):
    from app import create_app

    app = create_app()
    with app.app_context():
        if reset:
            db.drop_all()
        db.create_all()
        seed_badges()
        seed_kids()

        packs = sorted(p for p in CONTENT_DIR.glob("*.json"))
        if not packs:
            print("No content packs found in content/")
            return
        for path in packs:
            added, updated = load_pack(path)
            print(f"  {path.name:28} {added:>3} new, {updated:>3} updated")

        print(f"\n{Lesson.query.count()} lessons, {Question.query.count()} questions in the database.")


if __name__ == "__main__":
    run(reset="--reset" in sys.argv)
