# 12. Judge calibration

## What it does
Calibration asks how far the judge can be trusted. The owner hand-grades about 30 answers without seeing the judge's verdicts, using the same evidence the judge saw (including the figure images). Then `agreement` compares the two sets of grades for correctness and faithfulness. It reports raw agreement (the share of identical grades) and Cohen's kappa, which is `(p_o - p_e) / (1 - p_e)`, where `p_e` is the agreement two raters would reach by chance given their own grade frequencies. Raw agreement flatters a judge when one grade dominates. Kappa is `None` when both raters only ever gave one grade. Each calibration entry records the judge model and a fingerprint (a SHA-256 over the model, the output cap and the rendered prompt, first 12 hex characters). `agreement` refuses a file that mixes judges, and the release check blocks if the fingerprint differs from the final run's. The gate is the worse kappa of the two dimensions, at 0.60 or more. Today kappa treats 0.5 and 1 as different labels, with no partial credit, and has no interval.

## Where it lives
- `src/multimodal_doc_rag/evals/calibration.py::cohens_kappa`
- `src/multimodal_doc_rag/evals/calibration.py::raw_agreement`
- `src/multimodal_doc_rag/evals/calibration.py::agreement`
- `src/multimodal_doc_rag/evals/calibration.py::interpret_kappa`
- `src/multimodal_doc_rag/evals/calibration.py::sample_entries`
- `src/multimodal_doc_rag/evals/judge.py::judge_fingerprint`
- `src/multimodal_doc_rag/evals/gates.py::check_calibration`
- `src/multimodal_doc_rag/evals/gates.py::calibration_problems`
- `src/multimodal_doc_rag/evals/agreement_stats.py::kappa_bootstrap_ci` (gap: stub)
- `src/multimodal_doc_rag/evals/agreement_stats.py::weighted_kappa` (gap: stub)

## What was chosen and why
ADR 0011 requires the judge to be measured against human grades. ADR 0016 turns that into a gate (kappa at least 0.60, on the worse dimension), because if the judge disagrees with the owner its correctness and faithfulness scores cannot be trusted. ADR 0017 sets the minimum at 25 hand grades. ADR 0019 ties calibration to one judge configuration. The fingerprint is computed, not a hand-kept version string, so it cannot drift from the code, and it changes when the system prompt or the message layout changes. A mismatch blocks release, as missing evidence does elsewhere. The cost is that any judge change, even a typo, means grading again. ADR 0020 says the calibration grades must be the owner's, even though the dev gold set was reviewed by Claude.

## Options rejected
| Option | Why rejected | When it would win |
|---|---|---|
| Raw agreement only | Flatters a judge when one grade dominates | Balanced grades, though kappa is still safer |
| Model name as "same judge" | Misses prompt changes, the likeliest change | If the prompt were frozen by design |
| Git commit as "same judge" | Unrelated commits land in between, so it would never match and would be overridden | Never for this purpose |
| Hand-kept prompt version string | Fails silently when someone forgets to bump it | A team with a release process |
| Warn instead of block on mismatch | A check that can be talked out of a "no" stops being a check | Exploratory runs |
| Weighted kappa or a kappa interval | Not built. Stubs exist for Toby to decide. | Small n, or when 0.5 should count as nearer to 1 than to 0 |

## Evidence
- `tests/test_evals_calibration.py` pins kappa and the agreement report.
- Not measured yet: the judge's kappa. No hand grades exist, and the baseline run that they sample from has not happened. To measure it, run `scripts/calibrate_judge.py sample --n 30`, grade, then `agreement`.
- With 25 to 30 grades, kappa will have a wide interval. That is why the stub for a bootstrap interval exists. Neither the interval width nor the effect of the 0 / 0.5 / 1 scale on kappa has been measured.

## Interview questions
1. Explain Cohen's kappa to someone who only knows percentages. Why is 90% agreement not enough?

**Your answer:**

2. Correctness is graded 0, 0.5 or 1. What does plain kappa do with that scale, and what would weighted kappa change?

**Your answer:**

3. You have 25 to 30 grades. How certain can you be that the true kappa is above 0.60? How would you show it?

**Your answer:**

4. Why is the judge fingerprint computed from a probe through the real prompt builder instead of a version number?

**Your answer:**

5. The owner graded without seeing the judge's verdicts. Why? And why must they see the same figure images?

**Your answer:**
