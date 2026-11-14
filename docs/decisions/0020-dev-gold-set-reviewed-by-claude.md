# 0020. The dev gold set is reviewed by Claude, not the owner (demo shortcut)

- **Status:** Accepted
- **Date:** 2026-11-14
- **Amends:** 0011 and 0018 for the **dev** split only. Held-out, figure questions, calibration and the gates are unchanged.

## Context
0011 and 0018 say a model drafts gold questions and the owner reviews every one. The 108 dev drafts (48 FAA and 60 10-K) were waiting on that review, and the review was blocking every later step: the smoke runs, the baseline, calibration and the held-out run. The owner reviewed one item (`faa-dev-001`). They then decided that this project is a demo and asked Claude Code to review the remaining 107, knowing this goes against the recommended practice. Opus 5.5 reviewed the 47 FAA drafts. Partway through, the owner asked for cheaper, faster subagents, so three Claude Sonnet 5.5 subagents reviewed the 60 10-K drafts. They worked from a written brief that restates the checklist plus the lessons from the FAA pass. Their decisions were applied by the Opus session, which spot-checked them first.

## Options considered
- **The owner reviews every item (the plan in 0011).** This is the strongest gold set, but it is slow, and it was the bottleneck.
- **Claude reviews and the owner spot-checks a sample.** Faster, and the spot-check measures how good the review was. But the owner still has work to do before anything can run.
- **Claude reviews everything, recorded as such (chosen).** Nothing waits on the owner. The cost is that a human no longer stands between the drafter and the scores.
- **Skip review and run with `--include-drafts`.** Free, but the report would be marked as a smoke test, and the gold pages would be untrimmed and incomplete.

## Decision
- The reviewing model applies the same review checklist the owner would have used (`evals/README.md`, "Reviewing a draft"). For each item it:
  - checks the gold pages against the database;
  - adds other pages that also answer (exact-string and full-text search across every document, held-out included);
  - trims reference answers to what the question asks;
  - rewrites questions that are ambiguous or echo the passage;
  - checks each unanswerable against the whole collection.
- Decisions go through the project's own review functions (`verify`, `reject`, `with_changes`), so the split check still runs on every verified item.
- **Every item Claude decides is tagged** in `notes` with the model that reviewed it: `reviewer=claude-opus-5-5 (ADR 0020)` for FAA, `reviewer=claude-sonnet-5-5 (ADR 0020)` for 10-K. The tag is followed by the reason for any edit or rejection. `origin` stays `llm_draft`. `faa-dev-001`, which the owner reviewed, is untouched.
- Rejected drafts are not topped up automatically. Drafting more spends the capped key, so that waits for the owner.

## Why
- **The owner made the call,** for demo purposes, and accepted the trade-off.
- **The trade-off.** Drafter (Haiku 5.5), reviewers (Opus 5.5 and Sonnet 5.5) and default generator (Haiku 5.5) are now all Claude models. Haiku was deliberately not used as a reviewer, because it would be checking its own drafts and the answers it will be scored on. Only the judge (GPT-6 Luna, 0014) is outside that family. Two risks follow:
  - A Claude reviewer may share the drafter's and generator's blind spots. It may keep questions Claude finds easy and miss errors Claude would also make.
  - The independent check that 0011 counted on is gone for dev.
- **Why the damage is limited to dev.** Dev numbers are for tuning, and every report labels them as guidance. Release decisions bind only on held-out (0016).

## Consequences
- **Dev scores are evidence about the system as judged against a Claude-reviewed key, not a human-reviewed one.** Reports, the data card and the system card must say so.
- **Calibration hand grades must still come from the owner.** If Claude graded them, Cohen's kappa would measure Claude against the judge, not a human against the judge. That would make the calibration gate meaningless.
- **Held-out review is still open.** If held-out is also reviewed by Claude, write a further record. The release check would then rest on no human-reviewed questions at all, and the system card would have to say so.
- **The owner can upgrade any item later** by reviewing it and replacing the tag in `notes`. A spot-check of about 15 items would measure how often the owner disagrees with Claude's review.
