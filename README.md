# Quest Lab

A self-hosted learning app for two kids — maths, science and practical life skills,
with the lesson and its quiz in the same place. Python (Flask) on top of Postgres,
or SQLite if you just want it running on the kitchen laptop.

- **84 lessons, 12 boss challenges, 84 hands-on activities, 1176 questions.**
- Maths and Science mapped to **Australian Curriculum v9** content descriptions, at Year 4 and Year 6.
- Practical strands with no curriculum to answer to: **money and budgeting**, **home and tools**, **digital and data literacy**.
- Every lesson: a short read with worked examples, a recap, then **12 questions** — 8 core plus
  4 multi-step challenge questions — marked instantly with an explanation on every one.
- **A lesson is not finished until the quiz is passed and the activity is signed off.** Every
  lesson has a real-world task that has to actually be done, with measurements and a written
  account typed back in and approved by a parent.
- **Boss challenges** — 14 hard mixed questions per strand, locked until every lesson behind
  them is mastered.
- Per-kid profiles, XP, levels, day streaks, 19 badges, and a PIN-protected parent dashboard
  with the sign-off queue at the top of it.

---

## Run it locally in two minutes

```bash
pip install -r requirements.txt
python seed.py --reset      # builds the database and loads the content
python app.py               # http://localhost:5000
```

With no `DATABASE_URL` set it uses a SQLite file (`questlab.db`) sitting next to the code.
Nothing else to configure. Other devices on your home WiFi can reach it at
`http://<your-computer's-IP>:5000`.

First run creates two profiles, **Kid One** (Year 4) and **Kid Two** (Year 6).
Rename them in the parent dashboard, or add more from the front page.

The parent dashboard is at `/parent`. **Default PIN is 1234** — change it (see below).

---

## Run it on Postgres

```bash
export DATABASE_URL="postgresql://user:password@localhost:5432/questlab"
export SECRET_KEY="something long and random"
export PARENT_PIN="4821"
python seed.py              # creates tables and loads content
gunicorn "app:create_app()"
```

`postgres://` URLs (Heroku/Railway style) are rewritten automatically.
`seed.py` is safe to re-run: it matches lessons on `slug` and updates them in place,
so refreshing content never touches profiles, scores or streaks. Only `--reset` wipes things.

### Deploying

**[DEPLOY.md](DEPLOY.md) is the full walkthrough** — GitHub repo, then a Kamatera (or any
Ubuntu) server with Postgres, gunicorn under systemd, nginx and a Let's Encrypt certificate.
It's mostly two commands: `deploy/setup-server.sh` once, then `deploy/update.sh` whenever
you push a change.

`Procfile` and `railway.json` are also included if you'd rather use a platform host —
Railway, Render or Fly will pick the repo up, add Postgres, and run `seed.py` then gunicorn.
Health check endpoint: `/healthz`.

There are no per-kid logins. On anything reachable from the internet, set
`HOUSEHOLD_PASSWORD` — one shared password over the whole site, remembered for 180 days per
device, so the kids type it once.

---

## Environment variables

| Variable | Default | What it does |
|---|---|---|
| `DATABASE_URL` | SQLite file | Postgres connection string |
| `SECRET_KEY` | `change-me-in-production` | Signs the session cookie. Set a real one. |
| `PARENT_PIN` | `1234` | Unlocks `/parent` |
| `HOUSEHOLD_PASSWORD` | unset | Shared password over the whole site. Unset = no gate (local use). |
| `HTTPS_ONLY` | `false` | `true` behind HTTPS, so the session cookie is never sent in the clear |
| `PASS_MARK` | `90` | Percentage needed on a lesson quiz before it counts |
| `PORT` | `5000` | Port to bind |

---

## Adding your own lessons

Content lives in `content/*.json` — one file per pack, plain JSON, no database editing.
`content/_SCHEMA.md` documents every field, and you can copy any existing lesson as a
starting point.

```bash
python validate_content.py   # catches bad JSON, missing fields, mc answers not in choices
python seed.py               # loads the changes; scores and streaks are untouched
```

Each lesson needs 12 questions (the last 4 at `"difficulty": 4`) and one `activity` block.
`content/_SCHEMA.md` spells out the activity fields — materials, steps, and the `record`
fields the kid fills in, where every number has a plausible range and every written answer has
a minimum length. Boss packs (`boss_*.json`) use `"kind": "boss"` and a `covers` list naming
the strands that unlock them.

Four question types are supported:

- `mc` — multiple choice, the answer string must exactly match one of the choices
- `tf` — true/false
- `numeric` — a number, with an optional `tolerance` and `unit`
- `text` — a list of accepted spellings, matched case-insensitively

Set `year_level` to 4 or 6. A kid only sees lessons at their own year level, but the
lesson list has a Year 4 / Year 6 toggle if the older one wants to go back over something
or the younger one wants a stretch.

---

## What's in the content library

| Pack | Lessons | Covers |
|---|---|---|
| `maths_y4` | 14 | Place value and decimals, odd/even, fractions, ×÷ by powers of 10, estimation and rounding with money, algorithms, unknown values, times tables, measuring, perimeter and area, duration, angles — AC9M4N01–N09, A01–A02, M01–M04 |
| `maths_y6` | 14 | Integers, primes and squares, equivalent fractions, decimal arithmetic, percentages and discounts, modelling, growing patterns, order of operations, metric conversion, area, timetables, angle relationships — AC9M6N01–N09, A01–A02, M01–M04 |
| `science_y4` | 10 | Food chains and webs, the water cycle and catchments, contact forces and friction, gravity and magnetism, materials and their properties, fair tests, data and scientific explanation — AC9S4U01–U04, I02, H01 |
| `science_y6` | 10 | Habitats and physical conditions, adaptations, Earth's tilt and seasons, the Moon and tides, electrical circuits, energy at home, reversible and irreversible change, corrosion, variables and repeat trials, how science builds on itself — AC9S6U01–U04, I03, H01 |
| `practical_money` | 12 | Notes and coins, 5c rounding, change, unit pricing, wants vs needs, saving goals, earning; then budgets, discounts, GST and receipts, cards and tracking, interest, and spotting a rip-off |
| `practical_home` | 12 | Measuring, hand tools, fasteners, following instructions, kitchen measurement, looking after gear; then marking out and cutting, reading a plan, costing a small build, hazard spotting and PPE, basic repairs, knots and securing a load |
| `practical_digital` | 12 | Reading charts, tables and tallies, sequences, if/then, passwords, what to keep private; then mean/median/mode, misleading graphs, checking sources, loops and variables, scams and phishing, what a chatbot actually does |
| `boss_maths` | 4 | Number, and Algebra + Measurement, at each year level |
| `boss_science` | 2 | One per year level, across all six science strands |
| `boss_practical` | 6 | One per practical strand per year level |

Questions and examples use Australian money, metric units and Far North Queensland
context — wet season rainfall, the Endeavour River, mango season, road trains, rust in
the humidity — so the maths lands on things they actually see.

Practical lessons involving tools stay inside what a child can safely do with an adult
nearby: no mains electricity, no power tools used alone, no chemicals past household
cleaners.

---

## Checking it still works

```bash
python validate_content.py   # content structure
python smoke_test.py         # walks a test profile through lessons, quizzes and the dashboard
```

`smoke_test.py` renders every lesson page, plays a perfect quiz and a zero quiz, checks XP,
streaks, mastery and badge awards, starts a review mix, and confirms the parent dashboard
is PIN-gated. It creates a throwaway profile and deletes it afterwards.

---

## How a lesson gets finished

Two things, both required:

1. **The quiz** — 12 questions. Two warm-ups, six standard, two stretch, then four challenge
   questions that need two or three connected steps and are mostly typed answers rather than
   multiple choice, so there is nothing to guess from. You need **90%** (11 of 12). The best
   attempt is the one kept, and retaking can only improve it.
2. **The activity** — the real-world task. They do it, type in what they measured or built and
   a short written account, and it lands in your sign-off queue. You approve it or send it
   back with a note. Until it's approved, the lesson shows as "activity to go", not mastered.

Only then does the lesson count, and boss challenges only unlock once every lesson behind
them counts.

The activity form rejects blanks, obviously impossible measurements (each number field has a
plausible range) and one-word write-ups before it ever reaches you, so what you're signing off
is at least a genuine attempt.

**If 90% is too steep**, set `PASS_MARK=80` in the environment and restart — everything else
stays as it is.

### Scoring

- Correct answers earn 8 / 12 / 18 / 26 XP by difficulty (warm-up, standard, stretch, challenge).
- A perfect quiz adds a 25 XP clean-sweep bonus.
- A signed-off activity is worth 30-60 XP depending on how much work it is.
- 250 XP per level.
- The day streak counts consecutive days with any activity at all, so a short session still counts.

## Files

```
app.py                Flask app, routes, badge rules, household password gate
models.py             SQLAlchemy models and answer marking
seed.py               loads content/*.json into the database
validate_content.py   content linter
smoke_test.py         end-to-end test
content/              the lesson packs, plus _SCHEMA.md
templates/  static/   pages and styling
deploy/               systemd unit, nginx site, server setup / update / backup scripts
.github/workflows/    run the tests on every push, and optionally deploy
DEPLOY.md             the server walkthrough
```

Note on updates: `seed.py` matches questions on their position within a lesson and updates
them in place rather than recreating them, so answer history and in-flight quizzes keep
pointing at valid rows. Postgres enforces that with foreign keys; SQLite doesn't, which is
why the test suite is worth running against Postgres (CI does).
