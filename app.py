"""Quest Lab — maths, science and practical skills for two kids.

Run locally:      python seed.py --reset && python app.py
Run in production: gunicorn "app:create_app()"
"""
import hmac
import os
import random
from datetime import date, datetime, timedelta, timezone

from flask import (Flask, abort, flash, redirect, render_template, request,
                   session, url_for)

from models import (PASS_MARK, Activity, ActivityLog, AnswerLog, Attempt,
                    Badge, DailyActivity, Kid, KidBadge, Lesson, Progress,
                    Question, db)

SUBJECTS = ["Maths", "Science", "Practical"]


# --------------------------------------------------------------------------
# app factory
# --------------------------------------------------------------------------
def database_url():
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        here = os.path.abspath(os.path.dirname(__file__))
        return "sqlite:///" + os.path.join(here, "questlab.db")
    # Heroku/Railway style prefix that SQLAlchemy 2 no longer accepts
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-me-in-production")
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url()
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}
    app.config["PARENT_PIN"] = os.environ.get("PARENT_PIN", "1234")

    # Shared household password over the whole site. Unset = no gate (local dev).
    app.config["HOUSEHOLD_PASSWORD"] = os.environ.get("HOUSEHOLD_PASSWORD", "").strip()
    app.config["SESSION_COOKIE_SECURE"] = os.environ.get("HTTPS_ONLY", "").lower() in ("1", "true", "yes")
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=180)

    db.init_app(app)
    register_gate(app)
    register_routes(app)

    @app.context_processor
    def inject_globals():
        return {"current_kid": current_kid(), "subjects": SUBJECTS,
                "today": date.today(), "pass_mark": PASS_MARK}

    @app.template_filter("para")
    def para(text):
        """Turn a content body into simple paragraphs, bullets and bold."""
        from markupsafe import Markup, escape
        out, bullets = [], []

        def flush():
            if bullets:
                out.append("<ul>" + "".join(f"<li>{b}</li>" for b in bullets) + "</ul>")
                bullets.clear()

        for block in (text or "").split("\n"):
            line = escape(block.strip())
            if not line:
                flush()
                continue
            while "**" in line:
                line = Markup(str(line).replace("**", "<strong>", 1).replace("**", "</strong>", 1))
            if str(line).startswith("- "):
                bullets.append(str(line)[2:])
            else:
                flush()
                out.append(f"<p>{line}</p>")
        flush()
        return Markup("".join(out))

    return app


# --------------------------------------------------------------------------
# household password gate
# --------------------------------------------------------------------------
def register_gate(app):
    """One shared password for the whole site, remembered for 180 days.

    Set HOUSEHOLD_PASSWORD to switch it on. With it unset (local development)
    nothing is gated and the app behaves exactly as before.
    """
    OPEN = {"gate", "static", "healthz"}

    @app.before_request
    def require_household_password():
        secret = app.config["HOUSEHOLD_PASSWORD"]
        if not secret or session.get("household_ok"):
            return None
        if request.endpoint in OPEN:
            return None
        return redirect(url_for("gate", next=request.full_path.rstrip("?")))

    @app.route("/gate", methods=["GET", "POST"])
    def gate():
        secret = app.config["HOUSEHOLD_PASSWORD"]
        if not secret or session.get("household_ok"):
            return redirect(url_for("pick"))

        wrong = False
        if request.method == "POST":
            given = request.form.get("password", "")
            if hmac.compare_digest(given, secret):
                session["household_ok"] = True
                session.permanent = True
                target = request.args.get("next") or url_for("pick")
                if not target.startswith("/"):       # never redirect off-site
                    target = url_for("pick")
                return redirect(target)
            wrong = True
        return render_template("gate.html", wrong=wrong), (401 if wrong else 200)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def current_kid():
    kid_id = session.get("kid_id")
    return db.session.get(Kid, kid_id) if kid_id else None


def require_kid():
    kid = current_kid()
    if kid is None:
        return None
    return kid


def progress_for(kid, lesson):
    row = Progress.query.filter_by(kid_id=kid.id, lesson_id=lesson.id).first()
    if row is None:
        row = Progress(kid_id=kid.id, lesson_id=lesson.id)
        db.session.add(row)
        db.session.commit()
    return row


def bump_daily(kid, answered=0, correct=0, xp=0):
    today = date.today()
    row = DailyActivity.query.filter_by(kid_id=kid.id, day=today).first()
    if row is None:
        row = DailyActivity(kid_id=kid.id, day=today, answered=0, correct=0, xp=0)
        db.session.add(row)
    row.answered = (row.answered or 0) + answered
    row.correct = (row.correct or 0) + correct
    row.xp = (row.xp or 0) + xp
    db.session.commit()


def award(kid, code):
    badge = Badge.query.filter_by(code=code).first()
    if badge is None:
        return None
    if KidBadge.query.filter_by(kid_id=kid.id, badge_id=badge.id).first():
        return None
    db.session.add(KidBadge(kid_id=kid.id, badge_id=badge.id))
    db.session.commit()
    return badge


def check_badges(kid):
    """Return the badges newly earned right now."""
    earned = []
    finished = Attempt.query.filter(Attempt.kid_id == kid.id, Attempt.finished_at.isnot(None),
                                    Attempt.total > 0)
    total_attempts = finished.count()
    perfects = finished.filter(Attempt.total > 0, Attempt.score == Attempt.total).count()
    answered = AnswerLog.query.join(Attempt).filter(Attempt.kid_id == kid.id).count()
    stretch = (AnswerLog.query.join(Attempt).join(Question, AnswerLog.question_id == Question.id)
               .filter(Attempt.kid_id == kid.id, AnswerLog.correct.is_(True),
                       Question.difficulty == 3).count())

    challenge = (AnswerLog.query.join(Attempt).join(Question, AnswerLog.question_id == Question.id)
                 .filter(Attempt.kid_id == kid.id, AnswerLog.correct.is_(True),
                         Question.difficulty == 4).count())

    mastered, bosses_beaten = {}, 0
    for row in Progress.query.filter_by(kid_id=kid.id).all():
        if row.lesson.kind == "boss":
            bosses_beaten += 1 if row.quiz_passed else 0
        elif row.state == "mastered":
            mastered[row.lesson.subject] = mastered.get(row.lesson.subject, 0) + 1

    approved = (ActivityLog.query.filter_by(kid_id=kid.id, status=ActivityLog.APPROVED).count())
    activities_here = (Activity.query.join(Lesson)
                       .filter(Lesson.year_level == kid.year_level).count())
    boss_count = Lesson.query.filter_by(kind="boss", year_level=kid.year_level).count()

    rules = [
        ("first_quiz",   total_attempts >= 1),
        ("perfect",      perfects >= 1),
        ("perfect_five", perfects >= 5),
        ("streak_3",     kid.streak >= 3),
        ("streak_7",     kid.streak >= 7),
        ("century",      answered >= 100),
        ("five_hundred", answered >= 500),
        ("maths_10",     mastered.get("Maths", 0) >= 10),
        ("science_10",   mastered.get("Science", 0) >= 10),
        ("practical_10", mastered.get("Practical", 0) >= 10),
        ("all_rounder",  all(mastered.get(s, 0) >= 1 for s in SUBJECTS)),
        ("stretch_10",   stretch >= 10),
        ("level_5",      kid.level >= 5),
        ("hands_on",     approved >= 1),
        ("hands_on_10",  approved >= 10),
        ("hands_on_all", activities_here > 0 and approved >= activities_here),
        ("challenger",   challenge >= 25),
        ("boss_down",    bosses_beaten >= 1),
        ("boss_all",     boss_count > 0 and bosses_beaten >= boss_count),
    ]
    for code, met in rules:
        if met:
            badge = award(kid, code)
            if badge:
                earned.append(badge)
    return earned


def attempt_questions(attempt):
    ids = attempt.question_ids or []
    found = {q.id: q for q in Question.query.filter(Question.id.in_(ids)).all()} if ids else {}
    return [found[i] for i in ids if i in found]


# ---- boss challenges -----------------------------------------------------
def boss_state(kid, boss):
    """(unlocked, done, still_to_go) for one boss challenge."""
    covered = (Lesson.query
               .filter(Lesson.kind == "lesson",
                       Lesson.subject == boss.subject,
                       Lesson.year_level == boss.year_level,
                       Lesson.strand.in_(boss.covers or []))
               .all())
    rows = {r.lesson_id: r for r in Progress.query.filter_by(kid_id=kid.id).all()}
    outstanding = [l for l in covered
                   if not (rows.get(l.id) and rows[l.id].state == "mastered")]
    return (not outstanding), len(covered) - len(outstanding), outstanding


def bosses_for(kid):
    """Every boss at this kid's year level, with its unlock state."""
    out = []
    for boss in (Lesson.query.filter_by(kind="boss", year_level=kid.year_level)
                 .order_by(Lesson.subject, Lesson.slug).all()):
        unlocked, done, outstanding = boss_state(kid, boss)
        row = Progress.query.filter_by(kid_id=kid.id, lesson_id=boss.id).first()
        out.append({"boss": boss, "unlocked": unlocked, "done": done,
                    "total": done + len(outstanding), "outstanding": outstanding,
                    "beaten": bool(row and row.quiz_passed),
                    "best": row.best_percent if row and row.best_total else None})
    return out


# ---- activities ----------------------------------------------------------
def log_for(kid, activity):
    return ActivityLog.query.filter_by(kid_id=kid.id, activity_id=activity.id).first()


def clean_activity_form(activity, form):
    """Validate what the kid typed. Returns (values, errors)."""
    values, errors = {}, {}
    for field in activity.record_fields or []:
        fid = field["id"]
        raw = (form.get(fid) or "").strip()
        label = field.get("label", fid)

        if not raw:
            errors[fid] = "Fill this one in."
            values[fid] = raw
            continue

        kind = field.get("type", "text")
        if kind == "number":
            try:
                value = float(raw.replace(",", "").replace("$", ""))
            except ValueError:
                errors[fid] = "That needs to be a number."
                values[fid] = raw
                continue
            low, high = field.get("min"), field.get("max")
            if low is not None and value < float(low):
                errors[fid] = f"That looks too small — check your measuring. ({label})"
            elif high is not None and value > float(high):
                errors[fid] = f"That looks too big — check your measuring. ({label})"
            values[fid] = int(value) if value == int(value) else value

        elif kind == "choice":
            options = field.get("options", [])
            if raw not in options:
                errors[fid] = "Pick one of the options."
            values[fid] = raw

        else:
            need = int(field.get("min_words", 10))
            if len(raw.split()) < need:
                errors[fid] = f"Say a bit more — at least {need} words."
            values[fid] = raw

    return values, errors


# --------------------------------------------------------------------------
# routes
# --------------------------------------------------------------------------
def register_routes(app):

    # ---- profiles --------------------------------------------------------
    @app.route("/")
    def pick():
        kids = Kid.query.order_by(Kid.year_level).all()
        return render_template("pick.html", kids=kids)

    @app.route("/switch/<int:kid_id>")
    def switch(kid_id):
        kid = db.session.get(Kid, kid_id) or abort(404)
        session["kid_id"] = kid.id
        return redirect(url_for("home"))

    @app.route("/logout")
    def logout():
        session.pop("kid_id", None)
        session.pop("parent_ok", None)
        return redirect(url_for("pick"))

    @app.route("/kids/new", methods=["POST"])
    def kid_new():
        name = (request.form.get("name") or "").strip()[:60]
        if not name:
            flash("Give the profile a name.")
            return redirect(url_for("pick"))
        if Kid.query.filter_by(name=name).first():
            flash("There's already a profile with that name.")
            return redirect(url_for("pick"))
        year = 6 if request.form.get("year_level") == "6" else 4
        kid = Kid(name=name, year_level=year,
                  colour=request.form.get("colour", "teal"),
                  emoji=str(year))
        db.session.add(kid)
        db.session.commit()
        session["kid_id"] = kid.id
        return redirect(url_for("home"))

    @app.route("/kids/<int:kid_id>/rename", methods=["POST"])
    def kid_rename(kid_id):
        kid = db.session.get(Kid, kid_id) or abort(404)
        name = (request.form.get("name") or "").strip()[:60]
        if name:
            kid.name = name
        if request.form.get("year_level") in ("4", "6"):
            kid.year_level = int(request.form["year_level"])
            kid.emoji = request.form["year_level"]
        db.session.commit()
        return redirect(request.referrer or url_for("pick"))

    # ---- kid dashboard ---------------------------------------------------
    @app.route("/home")
    def home():
        kid = require_kid()
        if not kid:
            return redirect(url_for("pick"))

        rows = Progress.query.filter_by(kid_id=kid.id).all()
        by_lesson = {r.lesson_id: r for r in rows}

        cards = []
        for subject in SUBJECTS:
            lessons = Lesson.query.filter_by(subject=subject, kind="lesson",
                                             year_level=kid.year_level).all()
            done = sum(1 for l in lessons
                       if (r := by_lesson.get(l.id)) and r.state == "mastered")
            cards.append({
                "subject": subject,
                "total": len(lessons),
                "done": done,
                "percent": round(100 * done / len(lessons)) if lessons else 0,
            })

        everything = (Lesson.query.filter_by(year_level=kid.year_level, kind="lesson")
                      .order_by(Lesson.subject, Lesson.position).all())
        up_next = [l for l in everything
                   if not ((r := by_lesson.get(l.id)) and r.state == "mastered")][:3]

        # Lessons where the quiz is done but the activity still has to happen.
        waiting = []
        for lesson in everything:
            row = by_lesson.get(lesson.id)
            if row and row.state == "quiz-passed":
                waiting.append({"lesson": lesson, "status": row.activity_state})

        recent = (Attempt.query.filter(Attempt.kid_id == kid.id, Attempt.finished_at.isnot(None))
                  .order_by(Attempt.finished_at.desc()).limit(5).all())
        badges = (KidBadge.query.filter_by(kid_id=kid.id)
                  .order_by(KidBadge.earned_at.desc()).all())
        boss_rows = bosses_for(kid)

        return render_template("home.html", kid=kid, cards=cards, up_next=up_next,
                               waiting=waiting, recent=recent, badges=badges,
                               all_badges=Badge.query.all(),
                               boss_rows=boss_rows,
                               bosses_open=sum(1 for b in boss_rows if b["unlocked"] and not b["beaten"]))

    # ---- lesson browsing -------------------------------------------------
    @app.route("/learn")
    def learn():
        kid = require_kid()
        if not kid:
            return redirect(url_for("pick"))

        subject = request.args.get("subject") or "Maths"
        year = int(request.args.get("year") or kid.year_level)
        lessons = (Lesson.query.filter_by(subject=subject, year_level=year, kind="lesson")
                   .order_by(Lesson.position).all())
        rows = {r.lesson_id: r for r in Progress.query.filter_by(kid_id=kid.id).all()}

        grouped = {}
        for lesson in lessons:
            grouped.setdefault(lesson.strand, []).append((lesson, rows.get(lesson.id)))

        return render_template("learn.html", kid=kid, subject=subject, year=year,
                               grouped=grouped, count=len(lessons))

    @app.route("/lesson/<slug>")
    def lesson(slug):
        kid = require_kid()
        if not kid:
            return redirect(url_for("pick"))
        lesson = Lesson.query.filter_by(slug=slug).first() or abort(404)
        row = progress_for(kid, lesson)
        if row.read_at is None:
            row.read_at = datetime.now(timezone.utc)
            db.session.commit()
        return render_template("lesson.html", kid=kid, lesson=lesson, progress=row)

    # ---- the hands-on activity ------------------------------------------
    @app.route("/lesson/<slug>/activity", methods=["GET", "POST"])
    def activity(slug):
        kid = require_kid()
        if not kid:
            return redirect(url_for("pick"))
        lesson = Lesson.query.filter_by(slug=slug).first() or abort(404)
        if lesson.activity is None:
            return redirect(url_for("lesson", slug=slug))

        log = log_for(kid, lesson.activity)
        errors, values = {}, dict((log.responses if log else {}) or {})

        if request.method == "POST":
            if log and log.status == ActivityLog.APPROVED:
                return redirect(url_for("lesson", slug=slug))
            values, errors = clean_activity_form(lesson.activity, request.form)
            if not errors:
                if log is None:
                    log = ActivityLog(kid_id=kid.id, activity_id=lesson.activity.id, attempts=0)
                    db.session.add(log)
                log.responses = values
                log.status = ActivityLog.SUBMITTED
                log.submitted_at = datetime.now(timezone.utc)
                log.attempts = (log.attempts or 0) + 1
                log.parent_note = ""
                db.session.commit()
                progress_for(kid, lesson)
                flash("Sent off for checking. Once it's signed off the lesson counts.")
                return redirect(url_for("lesson", slug=slug))

        return render_template("activity.html", kid=kid, lesson=lesson,
                               activity=lesson.activity, log=log,
                               values=values, errors=errors)

    # ---- boss challenges -------------------------------------------------
    @app.route("/bosses")
    def bosses():
        kid = require_kid()
        if not kid:
            return redirect(url_for("pick"))
        return render_template("bosses.html", kid=kid, rows=bosses_for(kid))

    # ---- quizzes ---------------------------------------------------------
    @app.route("/lesson/<slug>/quiz", methods=["POST"])
    def start_quiz(slug):
        kid = require_kid()
        if not kid:
            return redirect(url_for("pick"))
        lesson = Lesson.query.filter_by(slug=slug).first() or abort(404)
        if lesson.kind == "boss":
            unlocked, _, outstanding = boss_state(kid, lesson)
            if not unlocked:
                flash(f"Still locked — {len(outstanding)} lesson(s) to master first.")
                return redirect(url_for("bosses"))
        ids = [q.id for q in lesson.questions]
        if not ids:
            flash("That lesson has no questions yet.")
            return redirect(url_for("lesson", slug=slug))
        attempt = Attempt(kid_id=kid.id, lesson_id=lesson.id, kind="lesson",
                          label=lesson.title, question_ids=ids, total=len(ids))
        db.session.add(attempt)
        db.session.commit()
        return redirect(url_for("quiz", attempt_id=attempt.id))

    @app.route("/mix", methods=["POST"])
    def start_mix():
        """A 10-question review mix, weighted to what this kid got wrong before."""
        kid = require_kid()
        if not kid:
            return redirect(url_for("pick"))
        subject = request.form.get("subject") or "Maths"

        pool = (Question.query.join(Lesson)
                .filter(Lesson.subject == subject, Lesson.year_level == kid.year_level,
                        Lesson.kind == "lesson").all())
        if not pool:
            flash("Nothing to review there yet.")
            return redirect(url_for("home"))

        wrong_ids = {row.question_id for row in
                     AnswerLog.query.join(Attempt)
                     .filter(Attempt.kid_id == kid.id, AnswerLog.correct.is_(False)).all()}
        missed = [q for q in pool if q.id in wrong_ids]
        rest = [q for q in pool if q.id not in wrong_ids]
        random.shuffle(missed)
        random.shuffle(rest)
        picked = (missed[:6] + rest)[:10]
        random.shuffle(picked)

        attempt = Attempt(kid_id=kid.id, lesson_id=None, kind="mix",
                          label=f"{subject} review mix",
                          question_ids=[q.id for q in picked], total=len(picked))
        db.session.add(attempt)
        db.session.commit()
        return redirect(url_for("quiz", attempt_id=attempt.id))

    @app.route("/quiz/<int:attempt_id>")
    def quiz(attempt_id):
        kid = require_kid()
        attempt = db.session.get(Attempt, attempt_id) or abort(404)
        if not kid or attempt.kid_id != kid.id:
            return redirect(url_for("pick"))
        if attempt.finished_at:
            return redirect(url_for("results", attempt_id=attempt.id))

        questions = attempt_questions(attempt)
        done = len(attempt.answers)
        if done >= len(questions):
            return redirect(url_for("finish", attempt_id=attempt.id))

        return render_template("quiz.html", kid=kid, attempt=attempt,
                               question=questions[done], index=done + 1,
                               total=len(questions), feedback=None)

    @app.route("/quiz/<int:attempt_id>", methods=["POST"])
    def answer(attempt_id):
        kid = require_kid()
        attempt = db.session.get(Attempt, attempt_id) or abort(404)
        if not kid or attempt.kid_id != kid.id:
            return redirect(url_for("pick"))

        questions = attempt_questions(attempt)
        done = len(attempt.answers)
        if attempt.finished_at or done >= len(questions):
            return redirect(url_for("finish", attempt_id=attempt.id))

        question = questions[done]
        if str(request.form.get("question_id")) != str(question.id):
            return redirect(url_for("quiz", attempt_id=attempt.id))  # stale form

        correct, tidied = question.check(request.form.get("response"))
        db.session.add(AnswerLog(attempt_id=attempt.id, question_id=question.id,
                                 response=tidied, correct=correct))
        gained = question.xp_value if correct else 0
        attempt.score = (attempt.score or 0) + (1 if correct else 0)
        attempt.xp_earned = (attempt.xp_earned or 0) + gained
        db.session.commit()
        bump_daily(kid, answered=1, correct=1 if correct else 0, xp=gained)

        return render_template("quiz.html", kid=kid, attempt=attempt, question=question,
                               index=done + 1, total=len(questions),
                               feedback={"correct": correct, "given": tidied, "xp": gained},
                               last=(done + 1 >= len(questions)))

    @app.route("/quiz/<int:attempt_id>/finish")
    def finish(attempt_id):
        kid = require_kid()
        attempt = db.session.get(Attempt, attempt_id) or abort(404)
        if not kid or attempt.kid_id != kid.id:
            return redirect(url_for("pick"))

        if not attempt.finished_at:
            attempt.finished_at = datetime.now(timezone.utc)
            attempt.total = len(attempt.question_ids or [])
            if attempt.total and attempt.score == attempt.total:
                attempt.xp_earned = (attempt.xp_earned or 0) + 25   # clean sweep bonus
            db.session.commit()

            if attempt.lesson_id:
                row = progress_for(kid, attempt.lesson)
                row.times_done = (row.times_done or 0) + 1
                row.last_at = attempt.finished_at
                if attempt.score > (row.best_score or 0) or not row.best_total:
                    row.best_score, row.best_total = attempt.score, attempt.total
                db.session.commit()

            session["new_badges"] = [b.code for b in check_badges(kid)]

        return redirect(url_for("results", attempt_id=attempt.id))

    @app.route("/results/<int:attempt_id>")
    def results(attempt_id):
        kid = require_kid()
        attempt = db.session.get(Attempt, attempt_id) or abort(404)
        if not kid or attempt.kid_id != kid.id:
            return redirect(url_for("pick"))
        if not attempt.finished_at:
            return redirect(url_for("finish", attempt_id=attempt.id))

        codes = session.pop("new_badges", [])
        new_badges = Badge.query.filter(Badge.code.in_(codes)).all() if codes else []
        return render_template("results.html", kid=kid, attempt=attempt,
                               answers=attempt.answers, new_badges=new_badges)

    # ---- parent dashboard ------------------------------------------------
    @app.route("/parent", methods=["GET", "POST"])
    def parent():
        if request.method == "POST" and request.form.get("pin"):
            if request.form["pin"] == app.config["PARENT_PIN"]:
                session["parent_ok"] = True
            else:
                flash("Wrong PIN.")
        if not session.get("parent_ok"):
            return render_template("parent_login.html")

        kids = Kid.query.order_by(Kid.year_level).all()

        # Everything waiting on a signature, oldest first — the top of the page.
        queue = (ActivityLog.query.filter_by(status=ActivityLog.SUBMITTED)
                 .order_by(ActivityLog.submitted_at).all())

        report = []
        for kid in kids:
            rows = Progress.query.filter_by(kid_id=kid.id).all()
            by_subject = {}
            for row in rows:
                if row.lesson.kind == "boss":
                    continue
                bucket = by_subject.setdefault(row.lesson.subject,
                                               {"mastered": 0, "waiting": 0,
                                                "practising": 0, "read": 0})
                state = row.state
                if state == "mastered":
                    bucket["mastered"] += 1
                elif state == "quiz-passed":
                    bucket["waiting"] += 1
                elif state == "practising":
                    bucket["practising"] += 1
                else:
                    bucket["read"] += 1

            strand_stats = {}
            logs = (AnswerLog.query.join(Attempt).join(Question, AnswerLog.question_id == Question.id)
                    .join(Lesson, Question.lesson_id == Lesson.id)
                    .filter(Attempt.kid_id == kid.id)
                    .with_entities(Lesson.subject, Lesson.strand, AnswerLog.correct).all())
            for subject, strand, correct in logs:
                key = (subject, strand)
                stat = strand_stats.setdefault(key, {"n": 0, "right": 0})
                stat["n"] += 1
                stat["right"] += 1 if correct else 0
            weakest = sorted(
                ({"subject": s, "strand": st, **v,
                  "pct": round(100 * v["right"] / v["n"])} for (s, st), v in strand_stats.items()
                 if v["n"] >= 5),
                key=lambda d: d["pct"])[:5]

            recent = (Attempt.query.filter(Attempt.kid_id == kid.id, Attempt.finished_at.isnot(None))
                      .order_by(Attempt.finished_at.desc()).limit(8).all())
            days = (DailyActivity.query.filter_by(kid_id=kid.id)
                    .order_by(DailyActivity.day.desc()).limit(14).all())

            report.append({"kid": kid, "by_subject": by_subject, "weakest": weakest,
                           "recent": recent, "days": list(reversed(days)),
                           "activities_done": ActivityLog.query.filter_by(
                               kid_id=kid.id, status=ActivityLog.APPROVED).count(),
                           "bosses": bosses_for(kid),
                           "badges": KidBadge.query.filter_by(kid_id=kid.id).all()})

        return render_template("parent.html", report=report, queue=queue,
                               pass_mark=PASS_MARK,
                               lesson_count=Lesson.query.filter_by(kind="lesson").count(),
                               boss_count=Lesson.query.filter_by(kind="boss").count(),
                               activity_count=Activity.query.count(),
                               question_count=Question.query.count())

    @app.route("/parent/signoff/<int:log_id>", methods=["POST"])
    def parent_signoff(log_id):
        if not session.get("parent_ok"):
            return redirect(url_for("parent"))
        log = db.session.get(ActivityLog, log_id) or abort(404)
        decision = request.form.get("decision")
        log.parent_note = (request.form.get("note") or "").strip()[:500]
        log.reviewed_at = datetime.now(timezone.utc)

        if decision == "approve":
            log.status = ActivityLog.APPROVED
            if not log.xp_awarded:
                log.xp_awarded = log.activity.xp
                bonus = Attempt(kid_id=log.kid_id, lesson_id=log.activity.lesson_id,
                                kind="activity", label=f"Activity: {log.activity.title}",
                                question_ids=[], score=0, total=0,
                                xp_earned=log.activity.xp,
                                finished_at=datetime.now(timezone.utc))
                db.session.add(bonus)
            db.session.commit()
            check_badges(log.kid)
            flash(f"Signed off — {log.kid.name} picked up {log.activity.xp} XP.")
        else:
            log.status = ActivityLog.RETURNED
            db.session.commit()
            flash(f"Sent back to {log.kid.name} to have another go.")

        return redirect(url_for("parent") + "#signoff")

    @app.route("/parent/logout")
    def parent_logout():
        session.pop("parent_ok", None)
        return redirect(url_for("pick"))

    @app.route("/healthz")
    def healthz():
        return {"ok": True, "lessons": Lesson.query.count()}


app = create_app()

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
