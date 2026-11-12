# 0019. Calibration is tied to one judge configuration

- **Status:** Accepted
- **Date:** 2026-11-11
- **Amends:** 0011 (judge calibration) and 0016 (what the release check accepts). It applies 0017's "one system" rule to the judge. Every threshold and evidence minimum is unchanged.

## Context
The `judge_kappa` gate (0016) says how far the LLM judge agrees with the owner's hand grades. That number is only evidence about the judge that was graded. Change the judge's prompt, model or output cap, and the kappa describes a grader that no longer exists, while the correctness and faithfulness gates on the final run are scored by a different one.

Nothing checked this. Calibration files didn't record which judge produced their verdicts, and `release_check.py` accepted any calibration file. The governance README listed this as a known limitation and left the match to the owner's memory. 0017 had already closed the same gap for injection runs (they must match the final run's generator and settings). The judge had no equivalent check.

There is a realistic way for it to happen. Calibration runs on a dev report, and the held-out run comes later. In between, the judge prompt is the most likely thing to get tuned, for example after calibration shows the judge is too lenient on partial answers.

At the time of writing no eval has run and no calibration grades exist, so no file needs migrating and nothing here was chosen after seeing a score.

## Options considered
**How to identify "the same judge"**
- **The judge model name only.** Simple, and already in every report. It misses prompt changes, which are the most likely change.
- **The git commit of the run.** Exact, but too strict. Unrelated commits (docs, the gold set, other code) will land between calibration and the final run, so it would almost never match. In practice it would be overridden, which teaches ignoring the check.
- **A hand-maintained prompt version string.** Explicit and readable, but it relies on remembering to bump it, which is the failure this record is about.
- **A fingerprint computed from the judge itself.** A short hash of the model, the output cap and the rendered prompt. It changes exactly when the grader changes, and nobody has to remember anything. It is opaque (a hash, not a description) and only covers what it hashes.

**What to do when it doesn't match, or is missing**
- **Block, like every other evidence problem.** It's consistent with 0016's rule that missing evidence blocks. Re-calibrating costs about 30 hand grades.
- **Warn and let the owner decide.** It's more flexible, but a release check that can be talked out of a "no" stops being a check.

## Decision
- **Fingerprint.** `judge_fingerprint(model, max_tokens)` in `evals/judge.py` returns the first 12 hex characters of a SHA-256 over the model id, the output cap, and the messages `build_judge_messages` produces for a fixed probe. The probe is three items: one with a reference answer, one unanswerable, one injection, and each has a figure image. Because it goes through the real prompt builder, a change to the system prompt and a change to the user-message layout both change the fingerprint.
- **Recorded everywhere it's needed:**
  - `RunConfig.judge_fingerprint` is set by `run_eval.py` and shown in each report's configuration table.
  - `calibrate_judge.py sample` copies the judge model and fingerprint onto each calibration entry.
  - `agreement()` refuses a file that mixes grades from more than one judge configuration.
- **Release check.** `release_check.py` reports an evidence problem, which blocks release, when:
  - the calibration grades don't record a fingerprint, or
  - their fingerprint differs from the final run's, or the final run didn't record one.

## Why
- **Calibration measures a grader, not a model name.** The prompt is part of the grader. A rubric change can move the kappa as much as a model change can.
- **Computed beats remembered.** A version string fails silently on the day someone forgets to bump it. The fingerprint can't drift from the code it describes.
- **Fail closed, as with the rest of the release check.** An unknown or mismatched judge is missing evidence, and 0016 decided missing evidence blocks. The cost of complying is bounded: about 30 hand grades.

**What we trade away:**
- **Any change re-triggers calibration.** A change to the judge prompt, even a typo fix, means grading again before release. That's deliberate.
- **The fingerprint is opaque.** It says that two judges differ, not how. The model name is recorded beside it to help.
- **Coverage is limited to model, cap and prompt.** Other request settings are not hashed. Today the judge sends no other settings, and the docstring says to add any that appear later (`reasoning`, `temperature`).
- **The provider can still change behind the same model id.** A model update on OpenRouter's side keeps the same fingerprint. No client-side check can see that.

## Consequences
- **Calibrate last.** The practical order is: settle the judge prompt on dev, calibrate against a run made with that judge, and don't touch the judge again before the held-out run. `evals/README.md` says so.
- **Changing the probe changes every fingerprint.** It invalidates existing grades, so the probe should be left alone.
- **The control matrix lists this as C12.**
- **Revisit if** the judge call gains request settings, the judge becomes an ensemble, or a provider starts publishing model version hashes that could replace the model id in the fingerprint.
