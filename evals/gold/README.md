Gold sets live here as `10k.jsonl` and `faa.jsonl`, created by `scripts/draft_gold.py`.
See ../README.md. Items count in a run only once their status is `verified`.

# Targets (ADR 0018)

Verified items per category. Check progress with `uv run python scripts/draft_gold.py count --corpus faa`.

| Corpus | Split | Unanswerable | Figure | Fact (table) | Fact (prose) | Concept | Total |
|---|---|---|---|---|---|---|---|
| faa | dev | 6 | 15 | – | 21 | 18 | 60 |
| faa | heldout (Ch. 11 ≈ 8, Ch. 13 ≈ 7, Ch. 15 ≈ 3) | 2 | 6 | – | 7 | 5 | 20 |
| 10k | dev (18 per company) | 6 | – | 24 | 12 | 18 | 60 |
| 10k | heldout (Costco) | 2 | – | 8 | 4 | 6 | 20 |

The held-out evidence minimums (`../gates.toml`) are 15 answerable per corpus and 3 unanswerable
pooled. The targets leave 3 and 1 spare.

## Order

Do the **held-out** items first, before any dev eval has run, so no score can steer them.

## Commands

Each draft run over-drafts (about 1.4×), because review rejects some. Top up with a new `--seed`:
chunks that already seeded an item are skipped.

```bash
# Handbook held-out: 12 fact/concept + 2 unanswerable, then 6 figure questions by hand
uv run python scripts/draft_gold.py draft --corpus faa --split heldout --n 20 --unanswerable 4
uv run python scripts/draft_gold.py add --corpus faa --split heldout --type figure

# 10-K held-out (Costco): 18 answerable + 2 unanswerable
uv run python scripts/draft_gold.py draft --corpus 10k --split heldout --n 28 --unanswerable 4

# Handbook dev: 39 fact/concept + 6 unanswerable, then 15 figure questions by hand
uv run python scripts/draft_gold.py draft --corpus faa --split dev --n 60 --unanswerable 9
uv run python scripts/draft_gold.py add --corpus faa --type figure

# 10-K dev: 54 answerable + 6 unanswerable. Table chunks are ~25% of a filing, so top up
# the table facts with --kind table (or write them: add --type fact --table).
uv run python scripts/draft_gold.py draft --corpus 10k --split dev --n 80 --unanswerable 9
uv run python scripts/draft_gold.py draft --corpus 10k --split dev --n 15 --kind table --seed 1

uv run python scripts/draft_gold.py review --corpus faa      # then --corpus 10k
uv run python scripts/draft_gold.py count --corpus faa
```

## Review rules

- **Mix:** the drafting model picks fact or concept, so reach the targets by rejecting surplus.
- **Table marker:** keep `source: table` in the notes of a table question when you edit them.
  `count` relies on it.
- **Unanswerable:** reject any question a document in the index answers. That includes Costco and
  handbook Ch. 11, 13 and 15, which are held out from tuning but searched like everything else.
  Aim for about a third each of: wrong period or entity; the topic is covered but the number isn't
  reported; an adjacent topic the documents never discuss.
- **Figure questions** (you write them): the answer must need the figure.
  - At least 4 of the 15 dev figure questions should have answers visible in the image but **not
    in the stored description**. Check the description in the database. Without these, the
    `--no-figure-images` comparison can't show anything.
  - Skip the 3 figures that stayed caption-only after the ingest.
  - Good dev chapters: Ch. 4 (Standard Atmosphere table), Ch. 8 (instruments), Ch. 10 (weight and
    balance), Ch. 14 (airport signs and markings), Ch. 16 (chart symbols).
  - Held-out: mostly Ch. 11's performance charts.
- **Never drafted from:** `phak-front` and `phak-index` (navigation, not content). They are still
  searched.
