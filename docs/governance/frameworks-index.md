# Frameworks index

Draft for owner review (2026-11-26)

One table of every governance file, with the framework or law each one serves. The existing [governance README](README.md) is not edited, so this index stands beside it. Framework choices come from [ADR 0016](../decisions/0016-governance-and-release-gates.md). Release gates live outside this folder, in [`evals/gates.toml`](../../evals/gates.toml).

| File | What it is | Serves | Status |
|---|---|---|---|
| [README.md](README.md) | Overview, frameworks, release gates in a paragraph | NIST AI RMF (structure), OWASP LLM Top 10 2026, EU AI Act classification | Existing |
| [data-card.md](data-card.md) | Sources, rights, personal data, what leaves the machine | NIST MAP and MEASURE (data), UK and EU GDPR (input to [gdpr.md](gdpr.md)), ISO/IEC 42001 A.7 | Existing, done |
| [control-matrix.md](control-matrix.md) | Controls C1 to C43, code and tests, status | OWASP LLM Top 10 2026, NIST AI RMF | Existing, draft awaiting owner review |
| [risk-register.md](risk-register.md) | Risks R1 to R12, ratings, mitigations | NIST AI RMF (Map), ISO/IEC 42001 clause 6 and A.5 (partial) | Existing, draft awaiting owner review |
| [nist-crosswalk.md](nist-crosswalk.md) | Controls mapped to AI RMF subcategories and AI 600-1 risks, with gaps | NIST AI RMF 1.0, NIST AI 600-1 | New, draft |
| [iso42001-crosswalk.md](iso42001-crosswalk.md) | Clauses 4 to 10 and Annex A areas against existing artifacts | ISO/IEC 42001:2023 (awareness only, not adopted) | New, draft |
| [gdpr.md](gdpr.md) | Roles, record of processing, transfers, rights, DPIA screening, privacy notice | UK GDPR, Data Protection Act 2018, EU GDPR. Not legal advice | New, draft |
| [system-card.md](system-card.md) | Intended use, models, limitations, evaluation placeholders | NIST MAP 1 and MAP 2 (check against source), ISO/IEC 42001 A.8 and A.9, EU AI Act Art. 50 (supporting) | New skeleton. Results filled after the held-out run |
| [incident-response.md](incident-response.md) | Severity levels, kill switches, steps, who is told | NIST MANAGE 4 (check against source), UK GDPR Art. 33 and 34, OWASP LLM06 (cost) | New skeleton |
| [human-oversight.md](human-oversight.md) | Who reviews what, how failures are found, what a person can override | NIST MAP 3.5 and GOVERN 3.2 (check against source), EU AI Act Art. 50 (Art. 14 noted as not applicable) | New, draft |
| [frameworks-index.md](frameworks-index.md) | This table | All | New |
| [`evals/gates.toml`](../../evals/gates.toml) | Pre-registered release gates and evidence minimums | NIST MEASURE and MANAGE (go/no-go) | Existing, frozen once the dev baseline exists |
| [`SECURITY.md`](../../SECURITY.md) | Vulnerability reporting and scope | OWASP LLM Top 10 2026, NIST GOVERN | Existing |
| [`docs/deployment.md`](../deployment.md) | Deploy steps, monitoring, spend cut-off | NIST MANAGE, OWASP LLM06 | Existing |
