"""Database models for Quest Lab.

Works on Postgres (production) and SQLite (local dev) without changes.
"""
import os
from datetime import date, datetime, timezone

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import JSON, UniqueConstraint

db = SQLAlchemy()

# Percentage needed on a lesson quiz before it counts. Override with PASS_MARK.
PASS_MARK = int(os.environ.get("PASS_MARK", "90"))


def utcnow():
    return datetime.now(timezone.utc)


class Kid(db.Model):
    __tablename__ = "kids"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), nullable=False, unique=True)
    year_level = db.Column(db.Integer, nullable=False, default=4)
    colour = db.Column(db.String(20), nullable=False, default="teal")
    emoji = db.Column(db.String(8), nullable=False, default="*")
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    attempts = db.relationship("Attempt", back_populates="kid", cascade="all, delete-orphan")
    progress = db.relationship("Progress", back_populates="kid", cascade="all, delete-orphan")
    activity = db.relationship("DailyActivity", back_populates="kid", cascade="all, delete-orphan")
    badges = db.relationship("KidBadge", back_populates="kid", cascade="all, delete-orphan")
    activity_logs = db.relationship("ActivityLog", back_populates="kid", cascade="all, delete-orphan")

    # ---- derived stats -------------------------------------------------
    @property
    def xp(self):
        return db.session.query(db.func.coalesce(db.func.sum(Attempt.xp_earned), 0)).filter(
            Attempt.kid_id == self.id
        ).scalar() or 0

    @property
    def level(self):
        """Level 1 at 0 XP, then every 250 XP."""
        return 1 + int(self.xp // 250)

    @property
    def xp_into_level(self):
        return int(self.xp % 250)

    @property
    def streak(self):
        """Consecutive days (ending today or yesterday) with any activity."""
        days = [
            d.day
            for d in DailyActivity.query.filter_by(kid_id=self.id)
            .order_by(DailyActivity.day.desc())
            .all()
        ]
        if not days:
            return 0
        today = date.today()
        if (today - days[0]).days > 1:
            return 0
        streak, cursor = 1, days[0]
        for d in days[1:]:
            if (cursor - d).days == 1:
                streak += 1
                cursor = d
            else:
                break
        return streak


class Lesson(db.Model):
    __tablename__ = "lessons"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(120), nullable=False, unique=True)
    pack = db.Column(db.String(60), nullable=False)
    kind = db.Column(db.String(12), nullable=False, default="lesson")   # lesson | boss
    covers = db.Column(JSON, default=list)      # boss only: the strands it unlocks from
    subject = db.Column(db.String(40), nullable=False)          # Maths | Science | Practical
    strand = db.Column(db.String(80), nullable=False)
    year_level = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(200), nullable=False)
    curriculum_code = db.Column(db.String(30), default="")
    curriculum_text = db.Column(db.Text, default="")
    position = db.Column(db.Integer, nullable=False, default=0)
    est_minutes = db.Column(db.Integer, default=12)
    intro = db.Column(db.Text, default="")
    sections = db.Column(JSON, default=list)
    key_points = db.Column(JSON, default=list)
    try_this = db.Column(db.Text, default="")

    questions = db.relationship(
        "Question", back_populates="lesson", cascade="all, delete-orphan",
        order_by="Question.position",
    )
    activity = db.relationship(
        "Activity", back_populates="lesson", cascade="all, delete-orphan", uselist=False,
    )

    @property
    def total_questions(self):
        return len(self.questions)

    @property
    def is_boss(self):
        return self.kind == "boss"


class Activity(db.Model):
    """The hands-on task attached to a lesson. Must be done and signed off."""
    __tablename__ = "activities"

    id = db.Column(db.Integer, primary_key=True)
    lesson_id = db.Column(db.Integer, db.ForeignKey("lessons.id"), nullable=False, unique=True)
    title = db.Column(db.String(200), nullable=False)
    why = db.Column(db.Text, default="")
    est_minutes = db.Column(db.Integer, default=25)
    adult_help = db.Column(db.String(12), default="none")       # none | nearby | required
    materials = db.Column(JSON, default=list)
    steps = db.Column(JSON, default=list)
    record_fields = db.Column(JSON, default=list)
    check_note = db.Column(db.Text, default="")
    xp = db.Column(db.Integer, default=40)

    lesson = db.relationship("Lesson", back_populates="activity")
    logs = db.relationship("ActivityLog", back_populates="activity", cascade="all, delete-orphan")

    ADULT_HELP_LABEL = {
        "none": "You can do this one on your own",
        "nearby": "Have an adult in earshot",
        "required": "An adult has to do this one with you",
    }

    @property
    def help_label(self):
        return self.ADULT_HELP_LABEL.get(self.adult_help, self.ADULT_HELP_LABEL["nearby"])


class ActivityLog(db.Model):
    """What a kid recorded when they did the activity, and whether it passed."""
    __tablename__ = "activity_logs"
    __table_args__ = (UniqueConstraint("kid_id", "activity_id", name="uq_log_kid_activity"),)

    SUBMITTED, APPROVED, RETURNED = "submitted", "approved", "returned"

    id = db.Column(db.Integer, primary_key=True)
    kid_id = db.Column(db.Integer, db.ForeignKey("kids.id"), nullable=False)
    activity_id = db.Column(db.Integer, db.ForeignKey("activities.id"), nullable=False)
    responses = db.Column(JSON, default=dict)                  # {field id: value}
    status = db.Column(db.String(12), default=SUBMITTED)
    parent_note = db.Column(db.Text, default="")
    submitted_at = db.Column(db.DateTime(timezone=True), default=utcnow)
    reviewed_at = db.Column(db.DateTime(timezone=True))
    attempts = db.Column(db.Integer, default=1)
    xp_awarded = db.Column(db.Integer, default=0)

    kid = db.relationship("Kid", back_populates="activity_logs")
    activity = db.relationship("Activity", back_populates="logs")

    @property
    def approved(self):
        return self.status == self.APPROVED

    def display_pairs(self):
        """(label, value) pairs in the order the activity asks for them."""
        out = []
        for field in (self.activity.record_fields or []):
            value = (self.responses or {}).get(field["id"], "")
            unit = field.get("unit", "")
            if unit and value != "":
                value = f"{value} {unit}"
            out.append((field["label"], value))
        return out


class Question(db.Model):
    __tablename__ = "questions"

    id = db.Column(db.Integer, primary_key=True)
    lesson_id = db.Column(db.Integer, db.ForeignKey("lessons.id"), nullable=False)
    position = db.Column(db.Integer, nullable=False, default=0)
    qtype = db.Column(db.String(12), nullable=False)            # mc | tf | numeric | text
    prompt = db.Column(db.Text, nullable=False)
    choices = db.Column(JSON, default=list)
    answer = db.Column(JSON)                                    # str | bool | float | list[str]
    tolerance = db.Column(db.Float, default=0.001)
    unit = db.Column(db.String(20), default="")
    explanation = db.Column(db.Text, default="")
    difficulty = db.Column(db.Integer, default=2)

    lesson = db.relationship("Lesson", back_populates="questions")
    logs = db.relationship("AnswerLog", back_populates="question", cascade="all, delete-orphan")

    # ---- marking -------------------------------------------------------
    def check(self, raw):
        """Return (is_correct, tidied_response_string)."""
        given = (raw or "").strip()
        if not given:
            return False, ""

        if self.qtype == "mc":
            return given == str(self.answer), given

        if self.qtype == "tf":
            truthy = given.lower() in ("true", "t", "yes", "1")
            return truthy == bool(self.answer), "True" if truthy else "False"

        if self.qtype == "numeric":
            cleaned = given.replace(",", "").replace("$", "").strip()
            try:
                value = float(cleaned)
            except ValueError:
                return False, given
            tol = self.tolerance if self.tolerance is not None else 0.001
            return abs(value - float(self.answer)) <= tol, given

        # text
        accepted = self.answer if isinstance(self.answer, list) else [self.answer]
        norm = given.lower().strip().rstrip(".")
        return any(norm == str(a).lower().strip() for a in accepted), given

    @property
    def answer_display(self):
        if self.qtype == "tf":
            return "True" if self.answer else "False"
        if isinstance(self.answer, list):
            return self.answer[0]
        if self.qtype == "numeric":
            value = float(self.answer)
            text = str(int(value)) if value == int(value) else str(value)
            return f"{text} {self.unit}".strip()
        return str(self.answer)

    DIFFICULTY_LABEL = {1: "Warm-up", 2: "Standard", 3: "Stretch", 4: "Challenge"}

    @property
    def xp_value(self):
        return {1: 8, 2: 12, 3: 18, 4: 26}.get(self.difficulty or 2, 12)

    @property
    def difficulty_label(self):
        return self.DIFFICULTY_LABEL.get(self.difficulty or 2, "Standard")


class Attempt(db.Model):
    __tablename__ = "attempts"

    id = db.Column(db.Integer, primary_key=True)
    kid_id = db.Column(db.Integer, db.ForeignKey("kids.id"), nullable=False)
    lesson_id = db.Column(db.Integer, db.ForeignKey("lessons.id"), nullable=True)
    kind = db.Column(db.String(12), default="lesson")            # lesson | mix
    label = db.Column(db.String(120), default="")
    question_ids = db.Column(JSON, default=list)
    started_at = db.Column(db.DateTime(timezone=True), default=utcnow)
    finished_at = db.Column(db.DateTime(timezone=True))
    score = db.Column(db.Integer, default=0)
    total = db.Column(db.Integer, default=0)
    xp_earned = db.Column(db.Integer, default=0)

    kid = db.relationship("Kid", back_populates="attempts")
    lesson = db.relationship("Lesson")
    answers = db.relationship("AnswerLog", back_populates="attempt", cascade="all, delete-orphan")

    @property
    def percent(self):
        return round(100 * self.score / self.total) if self.total else 0


class AnswerLog(db.Model):
    __tablename__ = "answer_logs"

    id = db.Column(db.Integer, primary_key=True)
    attempt_id = db.Column(db.Integer, db.ForeignKey("attempts.id"), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey("questions.id"), nullable=False)
    response = db.Column(db.Text, default="")
    correct = db.Column(db.Boolean, default=False)
    answered_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    attempt = db.relationship("Attempt", back_populates="answers")
    question = db.relationship("Question", back_populates="logs")


class Progress(db.Model):
    """One row per kid per lesson."""
    __tablename__ = "progress"
    __table_args__ = (UniqueConstraint("kid_id", "lesson_id", name="uq_progress_kid_lesson"),)

    id = db.Column(db.Integer, primary_key=True)
    kid_id = db.Column(db.Integer, db.ForeignKey("kids.id"), nullable=False)
    lesson_id = db.Column(db.Integer, db.ForeignKey("lessons.id"), nullable=False)
    read_at = db.Column(db.DateTime(timezone=True))
    best_score = db.Column(db.Integer, default=0)
    best_total = db.Column(db.Integer, default=0)
    times_done = db.Column(db.Integer, default=0)
    last_at = db.Column(db.DateTime(timezone=True))

    kid = db.relationship("Kid", back_populates="progress")
    lesson = db.relationship("Lesson")

    @property
    def best_percent(self):
        return round(100 * self.best_score / self.best_total) if self.best_total else 0

    @property
    def quiz_passed(self):
        return bool(self.best_total) and self.best_percent >= PASS_MARK

    @property
    def activity_log(self):
        activity = self.lesson.activity
        if activity is None:
            return None
        return ActivityLog.query.filter_by(kid_id=self.kid_id, activity_id=activity.id).first()

    @property
    def activity_state(self):
        """none | todo | submitted | returned | approved"""
        if self.lesson.activity is None:
            return "none"
        log = self.activity_log
        return log.status if log else "todo"

    @property
    def state(self):
        """A lesson is only mastered once the quiz is passed AND the activity signed off."""
        activity = self.activity_state
        if self.quiz_passed:
            if activity in ("none", "approved"):
                return "mastered"
            return "quiz-passed"
        if self.best_total:
            return "practising"
        if activity in ("submitted", "approved", "returned"):
            return "practising"
        return "read" if self.read_at else "new"

    STATE_LABEL = {
        "new": "Not started",
        "read": "Read",
        "practising": "Practising",
        "quiz-passed": "Quiz done, activity to go",
        "mastered": "Mastered",
    }

    @property
    def state_label(self):
        return self.STATE_LABEL.get(self.state, self.state)


class DailyActivity(db.Model):
    __tablename__ = "daily_activity"
    __table_args__ = (UniqueConstraint("kid_id", "day", name="uq_daily_kid_day"),)

    id = db.Column(db.Integer, primary_key=True)
    kid_id = db.Column(db.Integer, db.ForeignKey("kids.id"), nullable=False)
    day = db.Column(db.Date, nullable=False, default=date.today)
    answered = db.Column(db.Integer, default=0)
    correct = db.Column(db.Integer, default=0)
    xp = db.Column(db.Integer, default=0)

    kid = db.relationship("Kid", back_populates="activity")


class Badge(db.Model):
    __tablename__ = "badges"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(40), nullable=False, unique=True)
    name = db.Column(db.String(80), nullable=False)
    description = db.Column(db.String(200), nullable=False)
    icon = db.Column(db.String(8), default="*")


class KidBadge(db.Model):
    __tablename__ = "kid_badges"
    __table_args__ = (UniqueConstraint("kid_id", "badge_id", name="uq_kid_badge"),)

    id = db.Column(db.Integer, primary_key=True)
    kid_id = db.Column(db.Integer, db.ForeignKey("kids.id"), nullable=False)
    badge_id = db.Column(db.Integer, db.ForeignKey("badges.id"), nullable=False)
    earned_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    badge = db.relationship("Badge")
    kid = db.relationship("Kid", back_populates="badges")
