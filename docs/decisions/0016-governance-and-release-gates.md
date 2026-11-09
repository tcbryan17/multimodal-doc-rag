# 0016. Governance: NIST AI RMF + OWASP mapping, pre-registered release gates

- **Status:** Accepted (amended by [0017](0017-eval-validity.md): evidence minimums and run consistency; thresholds unchanged)
- **Date:** 2026-11-09

## Context
The eval (0011) *measures* the system. It doesn't say what counts as good enough to release, or show which safeguards exist and how we know they work. A reviewer, or an interviewer, will ask three questions:
1. Which risk framework is this held to?
2. What were the acceptance criteria, and were they set before the results were known?
3. Where is the evidence for each claimed control?

**Timing.** The ingest is done (step 14), but no gold set exists and no eval has run. This is the last point at which thresholds can be set without having seen a score. Pre-registration means writing the bar down first, so it can't drift to wherever the numbers landed.

**What the frameworks are (checked 2026-11-09):**
- **NIST AI RMF 1.0** organises AI risk work into four functions: Govern, Map, Measure and Manage. Its **Generative AI Profile (NIST AI 600-1, July 2024)** adds GenAI-specific risks and suggested actions. Both are voluntary, not certifications.
- **OWASP Top 10 for LLM Applications, 2026 edition** (August 2026) lists concrete application-security risks. Prompt injection and sensitive-information disclosure remain at the top.
- **ISO/IEC 42001:2023** is a certifiable AI *management system* standard, covering organisation-level policy, roles, audit and continual improvement.
- **EU AI Act.** The 2026 Digital Omnibus postponed the high-risk obligations. According to legal commentary, the Article 50 transparency duties (telling people they're interacting with an AI system) have applied since 2 August 2026. A public Q&A demo over public documents is not a high-risk use.

## Options considered
**Framework anchor**
- **NIST AI RMF + GenAI Profile for structure, OWASP LLM Top 10 for security controls, plus a short EU AI Act note.** Lightweight and widely recognised, and it maps directly onto controls and evals that already exist.
- **An ISO/IEC 42001-style management system.** Credible and certifiable, but built for organisations. For one person, policies, roles and internal audit would be mostly ceremony.
- **EU AI Act-led.** Legally precise, but most of the Act doesn't apply to a non-high-risk demo, so the write-up would be thin.
- **Our own checklist.** Fastest, but it can't be compared with anything a reviewer knows.

**Acceptance thresholds**
- **Pre-register and enforce in code.** Thresholds are committed now. A release check computes pass/fail from committed evidence and blocks release on any failure.
- **Pre-register in docs only.** This avoids moving the goalposts, but nothing enforces it.
- **Gate on the lower 95% CI bound.** The most rigorous option, but with about 20 held-out questions per corpus it is close to unpassable.
- **No thresholds.** Judge the numbers after the fact. This is the weakest assurance story.

**Which run binds**
- **The held-out final run.** It's the only unbiased number. It's noisy (about 20 questions per corpus), and a failure is reported, not retuned away.
- **Both dev and held-out.** The strictest option.
- **Dev only.** Larger n, but optimistic, because dev is the split we tune on.

## Decision
- **Frameworks:** NIST AI RMF 1.0 with the Generative AI Profile (AI 600-1) as the governance structure. The OWASP Top 10 for LLM Applications (2026) as the security control list. A short EU AI Act note covering classification and Article 50 transparency.
- **Release gates,** pre-registered in `evals/gates.toml` and checked by `scripts/release_check.py`. "Per corpus" means the 10-K and FAA corpora must **each** pass.

  | Gate | Threshold | Scope | Evidence |
  |---|---|---|---|
  | recall@5 | ≥ 0.80 | per corpus | held-out final report |
  | citation accuracy | ≥ 0.90 | per corpus | held-out final report |
  | faithfulness (judge) | ≥ 0.90 | per corpus | held-out final report |
  | correctness (judge) | ≥ 0.75 | per corpus | held-out final report |
  | false abstention | ≤ 0.10 | per corpus | held-out final report |
  | abstention on unanswerable | ≥ 0.80 | pooled | held-out final report |
  | answering cost, mean per question | ≤ $0.005 | per corpus | held-out final report |
  | latency p95 | ≤ 8,000 ms | per corpus | held-out final report |
  | injection: canary in answer | = 0 | pooled | injection reports (direct + indirect) |
  | judge vs. owner, Cohen's κ (worst dimension) | ≥ 0.60 | judge | calibration grades |
  | figure coverage (vision description completed) | ≥ 0.99 | index | the database |

  These numbers are the project's own bar, set before any result, not industry standards. A gate passes on the **point estimate**. The 95% CI is always reported next to it.
- **The binding run** is the one-time held-out final run. Dev runs show gate status as guidance while tuning. To count, the final run must be complete: held-out split, both corpora, judge on, verified items only, no `--limit`, not cut short by the cost cap, no item or judge errors, and a clean git tree.
- **Missing evidence fails.** A gate with no data (for example, no unanswerable items, or calibration not done) is reported as *not measured*, and that blocks release. An empty test never counts as a pass.
- **Artifacts** live in `docs/governance/`:
  - a **data card**, written now
  - a **control matrix** (control → framework item → where code enforces it → the test or report that proves it → implemented or planned), written alongside the eval
  - a **risk register**, written alongside the eval
  - a **system card**, filled in once the gate results exist
- **Sequencing:** gates and the data card come now, before the gold set. The control matrix and risk register come alongside the eval. Live-operations governance (whether and how long live `/ask` questions are logged, monitoring, incident response) is part of the deployment decision, which this record does not make.

## Why
- **Pre-registration is what makes the gates mean anything.** A threshold chosen after seeing a 0.83 is a description, not a test.
- **Enforcing the gates in code** turns "we have standards" into a check that can fail. Deployment can later run `release_check.py` as a required step.
- **Gating on held-out keeps the release decision unbiased.** The cost is noise. With about 2 unanswerable questions per corpus, abstention is pooled across corpora so that it measures something. Even so, one wrong answer among 4 unanswerable questions fails that gate. We accept that: it's strict in the safe direction.
- **NIST + OWASP** gives a structure a reviewer recognises without pretending to be an organisation-level ISO management system.
- **The κ gate guards the judged gates.** If the judge doesn't agree with a human, its correctness and faithfulness scores can't be trusted, so the release fails on that alone.

**What we trade away:**
- ISO 42001's audit trail.
- The rigour of lower-bound gating.
- The freedom to fix a held-out failure by retuning. A failure there means reporting it honestly, or writing a new ADR that explains the new configuration and why the held-out result is no longer clean.

## Consequences
- `evals/gates.toml` is frozen once the first dev baseline exists. Changing a threshold after that needs a new ADR that supersedes this one, with the reason stated.
- Dev runs print a "Release gates (guidance)" section, so tuning can be judged against the bar.
- `release_check.py` exits non-zero unless every gate passes on eligible evidence.
- The control matrix must mark each control **implemented** (with a pointer to code and a test) or **planned**. Rate limits, a read-only database role, a non-root container and query-log retention are planned until deployment.
- Revisit if NIST publishes a successor to AI 600-1, a new OWASP edition reorders the risks we map, or the deployment adds data flows (stored user questions) that need their own controls.
