# Content pack schema (read by seed.py)

Each file in `content/` is one JSON object:

```json
{
  "pack": "maths_y4",
  "subject": "Maths",
  "lessons": [ Lesson, Lesson, ... ]
}
```

`subject` is exactly one of: `Maths`, `Science`, `Practical`.

## Lesson object

```json
{
  "slug": "y4-decimals-tenths",
  "title": "Tenths, hundredths and the decimal point",
  "strand": "Number",
  "year_level": 4,
  "curriculum_code": "AC9M4N01",
  "curriculum_text": "recognise and extend the application of place value to tenths and hundredths ...",
  "position": 1,
  "est_minutes": 12,
  "intro": "One or two sentences, spoken straight to the kid, that make the topic feel worth doing.",
  "sections": [
    {
      "heading": "What a decimal point really means",
      "body": "2-5 short paragraphs. Plain language. Use **bold** for key terms. Blank line between paragraphs. Use `-` at line start for a bullet.",
      "example": {
        "prompt": "Write 3 and 45 hundredths as a decimal.",
        "working": ["3 whole ones stay left of the point", "45 hundredths = 4 tenths and 5 hundredths"],
        "answer": "3.45"
      }
    }
  ],
  "key_points": ["Short recap line", "Another one", "Three to five of these"],
  "try_this": "A 5-10 minute hands-on activity they can do at home with normal household stuff.",
  "questions": [ Question, ... ]
}
```

`example` is optional on a section. Use 3-5 sections per lesson.

## Question object

Four types. `difficulty` is 1 (warm-up), 2 (standard) or 3 (stretch).
Every question needs an `explain` that teaches the reasoning, not just the answer.

```json
{"type": "mc",      "prompt": "...", "choices": ["A", "B", "C", "D"], "answer": "B", "explain": "...", "difficulty": 2}
{"type": "tf",      "prompt": "...", "answer": true, "explain": "...", "difficulty": 1}
{"type": "numeric", "prompt": "...", "answer": 3.45, "tolerance": 0.001, "unit": "m", "explain": "...", "difficulty": 2}
{"type": "text",    "prompt": "...", "answer": ["condensation", "condensing"], "explain": "...", "difficulty": 2}
```

Rules:
- `mc`: 4 choices, `answer` must be the **exact string** of one of them. Wrong choices must be plausible (common mistakes), never joke options.
- `numeric`: `answer` is a number. `tolerance` optional (default 0.001). `unit` optional, shown next to the input box.
- `text`: `answer` is a list of accepted answers; matching is case-insensitive and ignores surrounding spaces. Keep accepted answers to one or two words.
- Aim for a 2 / 4 / 2 spread of difficulty 1 / 2 / 3 across a lesson's 8 questions.

---

# Difficulty 4 — the challenge tier

Questions may also be `"difficulty": 4`. These are the hardest in the app: multi-step,
worded like a real situation rather than a maths exercise, and deliberately not
multiple-choice wherever a `numeric` or `text` answer will do, so there is nothing to
guess from. A difficulty-4 question should take a capable kid at that year level two or
three connected steps to get through, and should not repeat a step already drilled in the
same lesson's easier questions.

Every lesson carries 4 of these, at positions 9-12, after the 8 core questions.

---

# The activity block

Every lesson has one `activity`: a hands-on task that has to actually be done in the real
world, with results typed back into the app and signed off by a parent. A lesson is not
finished until the quiz is passed **and** the activity is approved, so the activity has to
be genuinely doable at home, in one sitting, with ordinary stuff.

```json
"activity": {
  "title": "Measure the yard to the nearest tenth",
  "why": "One sentence: what doing this proves they can do that the quiz can't.",
  "est_minutes": 25,
  "adult_help": "none",
  "materials": ["tape measure or a metre ruler", "paper and pencil"],
  "steps": [
    "Numbered instructions, one per string. Say exactly what to do, not what to learn.",
    "Between 4 and 8 steps. The last step should be about recording the results."
  ],
  "record": [
    {"id": "length_m", "label": "How long is it, in metres?", "type": "number",
     "unit": "m", "hint": "one decimal place", "min": 0.5, "max": 60},
    {"id": "leftover", "label": "What did you do with the bit that wasn't a whole metre?",
     "type": "text", "hint": "two or three sentences", "min_words": 12},
    {"id": "tool", "label": "What did you measure with?", "type": "choice",
     "options": ["Tape measure", "Metre ruler", "Something else"]}
  ],
  "check": "One or two sentences telling the parent what a good result looks like and what to query.",
  "xp": 40
}
```

Rules:

- `adult_help` is `"none"`, `"nearby"` or `"required"`. Anything involving a sharp tool,
  a hot stove, a ladder or a power tool is `"required"`.
- `materials`: only things an ordinary Australian household has, or can find outside for
  free. Never anything that has to be bought.
- `record` has 3 to 5 fields, and **at least one `number` and at least one `text`**. The
  numbers must be things they actually measured, counted or worked out — never a fact they
  could copy from the lesson.
- `number` fields need a `min` and `max` wide enough for any honest answer but tight enough
  to catch a made-up one.
- `text` fields need `min_words` (10-40). Ask them to explain a decision or a surprise,
  not to restate the lesson.
- `xp` between 30 and 60, scaled to how much work it is.
- The activity must be different from that lesson's `try_this`, and harder.

---

# Boss challenge packs

A pack whose lessons have `"kind": "boss"` is a boss challenge — one per strand, unlocked
once every lesson in that strand is mastered. A boss lesson:

- has `"kind": "boss"` and a `"covers"` list of the strand names it draws on
- has exactly one section (a short brief telling them what they're in for) and no activity
- has 14 questions, all `difficulty` 3 or 4, that combine ideas from across the strand
  rather than testing one lesson at a time
- has `curriculum_code` `""`, and a `position` of 99
