"""End-to-end smoke test: walks a kid through lessons, quizzes and the dashboard.

    python smoke_test.py

Uses Flask's test client against whatever database DATABASE_URL points at
(SQLite by default). Creates a throwaway profile and deletes it afterwards.
"""
import random
import sys

from app import PASS_MARK, create_app
from models import (Activity, ActivityLog, AnswerLog, Attempt, Kid, Lesson,
                    Progress, Question, db)

app = create_app()
failures = []


def check(label, condition, detail=""):
    print(f"  {'ok  ' if condition else 'FAIL'}  {label}{'  — ' + detail if detail and not condition else ''}")
    if not condition:
        failures.append(label)


with app.app_context():
    lessons = Lesson.query.count()
    questions = Question.query.count()
    print(f"Database: {lessons} lessons, {questions} questions\n")
    check("content is loaded", lessons > 0 and questions > 0)

    # Every question can be marked, and its own correct answer marks correct.
    bad = []
    for q in Question.query.all():
        if q.qtype == "mc":
            given = str(q.answer)
        elif q.qtype == "tf":
            given = "True" if q.answer else "False"
        elif q.qtype == "numeric":
            given = str(q.answer)
        else:
            given = str(q.answer[0])
        ok, _ = q.check(given)
        if not ok:
            bad.append((q.id, q.qtype, q.prompt[:60]))
        # and a wrong answer must be marked wrong
        junk = ("False" if q.answer else "True") if q.qtype == "tf" else "zzzz-not-an-answer"
        wrong_ok, _ = q.check(junk)
        if wrong_ok:
            bad.append((q.id, q.qtype, "accepts nonsense: " + q.prompt[:50]))
    check("every question marks its own answer correct (and junk wrong)", not bad,
          "; ".join(str(b) for b in bad[:5]))

    kid = Kid.query.filter_by(name="Smoke Tester").first()
    if kid:
        db.session.delete(kid)
        db.session.commit()
    kid = Kid(name="Smoke Tester", year_level=4, colour="violet", emoji="4")
    db.session.add(kid)
    db.session.commit()
    kid_id = kid.id

client = app.test_client()
print()

with client.session_transaction() as sess:
    sess["kid_id"] = kid_id

check("profile picker loads", client.get("/").status_code == 200)
check("kid home loads", client.get("/home").status_code == 200)
for subject in ("Maths", "Science", "Practical"):
    r = client.get(f"/learn?subject={subject}")
    check(f"{subject} lesson list loads", r.status_code == 200)

with app.app_context():
    slugs = [l.slug for l in Lesson.query.filter_by(kind="lesson").order_by(Lesson.id).all()]
    all_slugs = [l.slug for l in Lesson.query.order_by(Lesson.id).all()]

# every lesson and boss page renders
broken = [s for s in all_slugs if client.get(f"/lesson/{s}").status_code != 200]
check(f"all {len(all_slugs)} lesson pages render", not broken, str(broken[:5]))


def play(slug, accuracy):
    """Answer a lesson's quiz, getting roughly `accuracy` of them right."""
    r = client.post(f"/lesson/{slug}/quiz", follow_redirects=False)
    attempt_id = int(r.headers["Location"].rstrip("/").split("/")[-1])
    with app.app_context():
        attempt = db.session.get(Attempt, attempt_id)
        qids = list(attempt.question_ids)
        qs = {q.id: q for q in Question.query.filter(Question.id.in_(qids)).all()}
        payloads = []
        for qid in qids:
            q = qs[qid]
            right = random.random() < accuracy
            if q.qtype == "mc":
                value = str(q.answer) if right else next(
                    (c for c in q.choices if c != q.answer), "nope")
            elif q.qtype == "tf":
                value = ("True" if q.answer else "False") if right else ("False" if q.answer else "True")
            elif q.qtype == "numeric":
                value = str(q.answer) if right else str(float(q.answer) + 7.77)
            else:
                value = str(q.answer[0]) if right else "definitely-not-it"
            payloads.append((qid, value))

    for qid, value in payloads:
        resp = client.post(f"/quiz/{attempt_id}",
                           data={"question_id": qid, "response": value})
        assert resp.status_code == 200, resp.status_code
    fin = client.get(f"/quiz/{attempt_id}/finish", follow_redirects=True)
    return attempt_id, fin


aid, page = play(slugs[0], 1.0)
check("perfect quiz finishes and shows results", page.status_code == 200)
with app.app_context():
    a = db.session.get(Attempt, aid)
    check("perfect score recorded", a.score == a.total and a.total > 0, f"{a.score}/{a.total}")
    check("clean-sweep bonus applied", a.xp_earned >= 25 + a.total * 8, str(a.xp_earned))

aid2, page2 = play(slugs[1], 0.0)
with app.app_context():
    a2 = db.session.get(Attempt, aid2)
    check("zero score recorded", a2.score == 0 and a2.xp_earned == 0)

# a partial run, then progress + badges
for slug in slugs[2:8]:
    play(slug, 0.9)

with app.app_context():
    kid = db.session.get(Kid, kid_id)
    check("XP accumulated", kid.xp > 0, str(kid.xp))
    check("streak counted today", kid.streak == 1, str(kid.streak))
    mastered = sum(1 for p in kid.progress if p.best_total and p.best_percent >= PASS_MARK)
    check("lessons marked mastered", mastered >= 1, str(mastered))
    codes = {kb.badge.code for kb in kid.badges}
    check("badges awarded", {"first_quiz", "perfect"} <= codes, str(sorted(codes)))

r = client.post("/mix", data={"subject": "Maths"}, follow_redirects=True)
check("review mix starts", r.status_code == 200 and b"Question 1 of" in r.data)

check("parent dashboard is PIN-gated", b"PIN" in client.get("/parent").data)
r = client.post("/parent", data={"pin": "1234"}, follow_redirects=True)
check("parent dashboard opens with the PIN", b"Coverage" in r.data)
check("health check responds", client.get("/healthz").status_code == 200)

# stale form submission must not double-count
r = client.post(f"/lesson/{slugs[9]}/quiz")
aid3 = int(r.headers["Location"].rstrip("/").split("/")[-1])
resp = client.post(f"/quiz/{aid3}", data={"question_id": 999999, "response": "x"})
with app.app_context():
    check("stale answer is ignored", db.session.get(Attempt, aid3).answers == [])

# ---------------------------------------------------------------------------
# Activities: they have to be done, written up, and signed off before a lesson
# counts. This is the part that can't be clicked through.
# ---------------------------------------------------------------------------
print()

with app.app_context():
    lessons_without = (Lesson.query.outerjoin(Activity)
                       .filter(Lesson.kind == "lesson", Activity.id.is_(None)).count())
    check("every lesson has an activity", lessons_without == 0, f"{lessons_without} without")
    bosses_with = (Lesson.query.join(Activity).filter(Lesson.kind == "boss").count())
    check("boss challenges have no activity", bosses_with == 0)
    check("challenge tier loaded",
          Question.query.filter_by(difficulty=4).count() >= 336,
          str(Question.query.filter_by(difficulty=4).count()))
    check("boss challenges loaded", Lesson.query.filter_by(kind="boss").count() == 12)


def good_answers(activity, *, sabotage=None):
    """Plausible values for an activity's record fields."""
    out = {}
    for f in activity.record_fields or []:
        kind = f.get("type", "text")
        if kind == "number":
            low, high = float(f["min"]), float(f["max"])
            out[f["id"]] = str(round((low + high) / 2, 2))
        elif kind == "choice":
            out[f["id"]] = f["options"][0]
        else:
            words = int(f.get("min_words", 10))
            out[f["id"]] = " ".join(["measured"] * (words + 2))
    if sabotage:
        out.update(sabotage)
    return out


with app.app_context():
    target = (Lesson.query.filter_by(kind="lesson", year_level=4, subject="Maths")
              .order_by(Lesson.position).first())
    target_slug, activity_id = target.slug, target.activity.id
    act = target.activity
    num_field = next(f for f in act.record_fields if f.get("type") == "number")
    txt_field = next(f for f in act.record_fields if f.get("type", "text") == "text")
    blank, over, short = {}, dict(), dict()
    over[num_field["id"]] = str(float(num_field["max"]) * 10 + 1000)
    short[txt_field["id"]] = "nup"
    good = good_answers(act)
    over_payload = good_answers(act, sabotage=over)
    short_payload = good_answers(act, sabotage=short)

check("activity page loads", client.get(f"/lesson/{target_slug}/activity").status_code == 200)

r = client.post(f"/lesson/{target_slug}/activity", data={})
check("empty activity submission is rejected", b"Fill this one in" in r.data)
r = client.post(f"/lesson/{target_slug}/activity", data=over_payload)
check("an impossible measurement is rejected", b"too big" in r.data)
r = client.post(f"/lesson/{target_slug}/activity", data=short_payload)
check("a one-word write-up is rejected", b"Say a bit more" in r.data)

with app.app_context():
    check("nothing was logged from the rejected attempts",
          ActivityLog.query.filter_by(kid_id=kid_id, activity_id=activity_id).first() is None)

r = client.post(f"/lesson/{target_slug}/activity", data=good, follow_redirects=True)
with app.app_context():
    log = ActivityLog.query.filter_by(kid_id=kid_id, activity_id=activity_id).first()
    check("a good submission is logged and waits for a signature",
          log is not None and log.status == "submitted")
    log_id = log.id

# Pass the quiz on that lesson too — it still must not count as mastered.
play(target_slug, 1.0)
with app.app_context():
    row = Progress.query.filter_by(kid_id=kid_id).join(Lesson).filter(
        Lesson.slug == target_slug).first()
    check("quiz passed but activity unsigned is NOT mastery",
          row.state == "quiz-passed", row.state)

# The parent signs it off.
client.post("/parent", data={"pin": "1234"})
r = client.get("/parent")
check("the sign-off queue shows the submission", b"Waiting on you" in r.data and b"Sign it off" in r.data)

r = client.post(f"/parent/signoff/{log_id}", data={"decision": "return", "note": "Measure it again"},
                follow_redirects=True)
with app.app_context():
    check("sending it back reopens it",
          db.session.get(ActivityLog, log_id).status == "returned")

client.post(f"/lesson/{target_slug}/activity", data=good, follow_redirects=True)
r = client.post(f"/parent/signoff/{log_id}", data={"decision": "approve", "note": "Good work"},
                follow_redirects=True)
with app.app_context():
    log = db.session.get(ActivityLog, log_id)
    check("signing off approves and pays the XP",
          log.status == "approved" and log.xp_awarded > 0, f"{log.status}/{log.xp_awarded}")
    row = Progress.query.filter_by(kid_id=kid_id).join(Lesson).filter(
        Lesson.slug == target_slug).first()
    check("quiz passed + activity signed off IS mastery", row.state == "mastered", row.state)
    codes = {kb.badge.code for kb in db.session.get(Kid, kid_id).badges}
    check("the hands-on badge is awarded", "hands_on" in codes, str(sorted(codes)))

# ---------------------------------------------------------------------------
# Boss challenges stay locked until the strand behind them is finished.
# ---------------------------------------------------------------------------
print()

with app.app_context():
    boss = Lesson.query.filter_by(slug="boss-maths-y4-measurement").first()
    boss_slug = boss.slug
    scope = (Lesson.query.filter(Lesson.kind == "lesson", Lesson.subject == "Maths",
                                 Lesson.year_level == 4,
                                 Lesson.strand.in_(boss.covers)).all())
    scope_slugs = [l.slug for l in scope]

check("boss list loads", client.get("/bosses").status_code == 200)
check("a locked boss is shown as locked", b"Locked" in client.get("/bosses").data)

before = None
with app.app_context():
    before = Attempt.query.filter_by(kid_id=kid_id).count()
client.post(f"/lesson/{boss_slug}/quiz", follow_redirects=True)
with app.app_context():
    check("a locked boss refuses to start",
          Attempt.query.filter_by(kid_id=kid_id).count() == before)


def finish_lesson(slug):
    """Pass the quiz and get the activity signed off."""
    play(slug, 1.0)
    with app.app_context():
        lesson = Lesson.query.filter_by(slug=slug).first()
        payload = good_answers(lesson.activity)
    client.post(f"/lesson/{slug}/activity", data=payload, follow_redirects=True)
    with app.app_context():
        lesson = Lesson.query.filter_by(slug=slug).first()
        log = ActivityLog.query.filter_by(kid_id=kid_id, activity_id=lesson.activity.id).first()
    client.post(f"/parent/signoff/{log.id}", data={"decision": "approve"}, follow_redirects=True)


for slug in scope_slugs:
    finish_lesson(slug)

with app.app_context():
    mastered = sum(1 for s in scope_slugs
                   if (p := Progress.query.filter_by(kid_id=kid_id).join(Lesson)
                       .filter(Lesson.slug == s).first()) and p.state == "mastered")
    check(f"all {len(scope_slugs)} lessons behind the boss are mastered",
          mastered == len(scope_slugs), f"{mastered}/{len(scope_slugs)}")

r = client.post(f"/lesson/{boss_slug}/quiz", follow_redirects=True)
check("the boss now starts", b"Question 1 of 14" in r.data)

with app.app_context():
    codes = {kb.badge.code for kb in db.session.get(Kid, kid_id).badges}
    check("challenge and activity badges accumulate",
          "challenger" in codes and "hands_on_10" not in codes or "challenger" in codes,
          str(sorted(codes)))

# Re-running the seeder over a database that already has answer history is what
# every deploy does. It must not break the history or fall over on a foreign key.
import seed as seeder

with app.app_context():
    before_logs = AnswerLog.query.count()
    try:
        for path in sorted((seeder.CONTENT_DIR).glob("*.json")):
            seeder.load_pack(path)
        reseeded = True
        detail = ""
    except Exception as exc:                                  # noqa: BLE001
        reseeded, detail = False, str(exc)[:120]
    check("re-seeding over existing answer history works", reseeded, detail)
    check("answer history survived the re-seed",
          AnswerLog.query.count() == before_logs,
          f"{AnswerLog.query.count()} vs {before_logs}")

with app.app_context():
    db.session.delete(db.session.get(Kid, kid_id))
    db.session.commit()
    check("deleting a profile cleans up after itself",
          db.session.get(Kid, kid_id) is None)

# The household password gate (only active when HOUSEHOLD_PASSWORD is set).
import os

os.environ["HOUSEHOLD_PASSWORD"] = "test-house-password"
gated = create_app().test_client()
r = gated.get("/home")
check("gate redirects a stranger", r.status_code == 302 and "/gate" in r.headers.get("Location", ""))
check("health check stays open through the gate", gated.get("/healthz").status_code == 200)
check("wrong password is refused",
      gated.post("/gate", data={"password": "not-it"}).status_code == 401)
r = gated.post("/gate?next=/home", data={"password": "test-house-password"})
check("right password lets you in", r.status_code == 302 and r.headers["Location"].endswith("/home"))
check("and you stay in", gated.get("/home").status_code in (200, 302))
fresh = create_app().test_client()
r = fresh.post("/gate?next=https://evil.example.com", data={"password": "test-house-password"})
check("open-redirect attempt is ignored", "evil.example.com" not in r.headers.get("Location", ""))
os.environ.pop("HOUSEHOLD_PASSWORD")

print()
if failures:
    print(f"{len(failures)} check(s) failed.")
    sys.exit(1)
print("All checks passed.")
