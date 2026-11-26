# ISO/IEC 42001 crosswalk

Draft for owner review (2026-11-26)

[ADR 0016](../decisions/0016-governance-and-release-gates.md) chose NIST AI RMF as the anchor for this project. It looked at an ISO/IEC 42001-style management system and rejected it as ceremony for one person: policies, roles and internal audit built for an organisation. This crosswalk does not change that. It shows awareness of ISO/IEC 42001:2023 by listing which existing artifacts touch each area, and where the project deliberately does not adopt a management system. Nothing here is a claim of conformity or certification.

The standard's text is copyrighted, so the areas below are described in my own words. Clause and annex numbering is from memory of the 2023 edition (check against source).

**Key.** Covered: an existing artifact does the job at demo scale. Partial: some of it exists. Out of scope: not adopted, with the reason.

## Management system clauses 4 to 10

| Clause | Area (own words) | Existing artifacts | Status |
|---|---|---|---|
| 4 | Context: who the system serves, what outside factors and requirements apply, and where the management system's boundary sits | [README](../../README.md) (scope), [governance README](README.md) (frameworks and EU AI Act classification), [data card](data-card.md) | Partial. There is a scope and a classification, but no formal list of interested parties or boundary statement. The [system card](system-card.md) skeleton adds intended use. |
| 5 | Leadership: top-level commitment, an AI policy, assigned roles | [ADR 0016](../decisions/0016-governance-and-release-gates.md), [ADR 0021](../decisions/0021-deployment-hosting-logging-and-review-owners.md) (named owners for reviews), [human-oversight.md](human-oversight.md) | Partial. The owner is the only role. There is no standalone AI policy document. Out of scope as a formal policy, because one person is the leadership. |
| 6 | Planning: addressing risks and opportunities, setting AI objectives, planning changes | [Risk register](risk-register.md), pre-registered [release gates](../../evals/gates.toml), [build plan](../build-plan.md) | Covered at demo scale. Risk register ratings are a draft awaiting review. |
| 7 | Support: resources, competence, awareness, communication, documented information | ADRs in [`docs/decisions/`](../decisions/README.md), `CLAUDE.md`, the governance folder | Partial. Documentation is strong. Training and competence records are out of scope for one person. |
| 8 | Operation: operational planning and control, AI risk assessment and treatment, AI system impact assessment | [Control matrix](control-matrix.md), [deployment runbook](../deployment.md), [SECURITY.md](../../SECURITY.md), [ADR 0023](../decisions/0023-pre-deploy-security-review.md) | Partial. Risk assessment and treatment exist. A formal impact assessment does not (see A.5). Operation controls are mostly planned until deployment. |
| 9 | Performance evaluation: monitoring and measurement, internal audit, management review | Eval harness and gates ([ADR 0011](../decisions/0011-eval-methodology.md), [0017](../decisions/0017-eval-validity.md)), `scripts/release_check.py`, `/stats` counters (planned until deployed) | Partial. Measurement is strong. Internal audit and management review are out of scope: one person cannot audit independently. The nearest substitute is the owner's review of held-out items ([ADR 0021](../decisions/0021-deployment-hosting-logging-and-review-owners.md)). |
| 10 | Improvement: handling nonconformity, corrective action, continual improvement | Superseding ADRs (an accepted record is never edited), [incident-response.md](incident-response.md) post-incident review | Partial. The ADR rule gives a trail of changes. Corrective-action tracking is informal. |

## Annex A control areas

| Area | What it is about (own words) | Existing artifacts | Status |
|---|---|---|---|
| A.2 Policies related to AI | Having AI-related policies, aligned with other policies and reviewed | ADRs, [governance README](README.md), `CLAUDE.md` working rules | Partial. Policies live as decisions and rules, not a policy document. |
| A.3 Internal organisation | Defined roles and responsibilities, and a way to report concerns | [human-oversight.md](human-oversight.md), [SECURITY.md](../../SECURITY.md) (private vulnerability reporting) | Partial. One owner holds every role. Out of scope: no separation of duties is possible. |
| A.4 Resources for AI systems | Documenting the data, tooling, compute and people the system relies on | [data card](data-card.md), [`config.py`](../../src/multimodal_doc_rag/config.py) (model ids), [ADR 0002](../decisions/0002-openrouter-for-all-model-calls.md), [ADR 0021](../decisions/0021-deployment-hosting-logging-and-review-owners.md) | Covered at demo scale. |
| A.5 Assessing impacts of AI systems | Assessing effects on individuals, groups and society, and keeping the record | [Risk register](risk-register.md) (likelihood and impact), [nist-crosswalk.md](nist-crosswalk.md) gaps | Partial. No separate impact assessment. A short impact note is the suggested proportionate response. |
| A.6 AI system life cycle | Objectives, design, verification and validation, deployment, operation, monitoring, documentation | [Build plan](../build-plan.md), ADRs, eval harness, [release gates](../../evals/gates.toml), [deployment runbook](../deployment.md) | Covered for design and verification. Deployment and operation are planned. |
| A.7 Data for AI systems | Data management, acquisition, quality, provenance and preparation | [data card](data-card.md), `scripts/fetch_corpus.py` (C33), SHA-256 in the manifest | Covered. Known gaps are listed in data card section 7. |
| A.8 Information for interested parties | Documentation for users, reporting of incidents, and communicating system information | AI notice (C15, planned), [system-card.md](system-card.md), [incident-response.md](incident-response.md), [gdpr.md](gdpr.md) (privacy notice, planned) | Partial. Nothing user-facing exists until deployment. |
| A.9 Use of AI systems | Rules for responsible use, intended use, and oversight of how the system is used | Disclaimer in the [README](../../README.md), [system-card.md](system-card.md) intended and out-of-scope use, rate limits (C26, planned) | Partial. Suggested for the system card. |
| A.10 Third-party and customer relationships | Allocating responsibility with suppliers, and checking supplier behaviour | OpenRouter and ZDR (C16), [ADR 0009](../decisions/0009-models-and-privacy.md), provider credit limits (C22), [gdpr.md](gdpr.md) (processors) | Partial. Supplier terms and DPAs are not yet on file. Customers: none, since this is a demo. |

## What this crosswalk is for

In an interview the honest line is: NIST AI RMF is the structure, OWASP is the security list, and ISO/IEC 42001 was read and set aside on purpose because the management-system parts (audit, management review, formal roles) need more than one person. The technical areas (data, life cycle, third parties) are covered by the artifacts above.
