# UK GDPR and EU GDPR

Not legal advice.

Draft for owner review (2026-11-26)

This note records how the demo handles personal data. It is written for the owner, who is UK-based. The UK GDPR and the Data Protection Act 2018 apply to the owner's processing. The EU GDPR may also apply to visitors in the EU (Art. 3(2): offering a service to people in the EU). The UK GDPR was amended by the Data (Use and Access) Act 2025, so check current UK text before relying on any article below (check against source).

Nothing is deployed yet. Every "planned" item below is a plan, not a fact about a running system. Article numbers are from memory of the UK and EU texts, which share the same numbering for the articles used here (check against source).

## 1. Scope and roles

- **Controller.** The owner decides why and how personal data is processed for the demo, so the owner is the controller. Scope here is the live demo and the local build. The legal entity (individual or company) is `TODO(owner): confirm`.
- **Processors (planned, none contracted yet):**
  - OpenRouter, which routes every model call ([ADR 0002](../decisions/0002-openrouter-for-all-model-calls.md)).
  - The model providers behind OpenRouter's zero-data-retention endpoints (for example the embedding, reranking and generation providers named in [ADR 0009](../decisions/0009-models-and-privacy.md)).
  - Fly.io, which runs the API container ([ADR 0021](../decisions/0021-deployment-hosting-logging-and-review-owners.md)).
  - Neon, which hosts Postgres. It holds public documents only, not visitor data.
- Whether each is a processor or an independent controller for some data is `TODO(owner): check each provider's terms`.
- **Other repo.** The `agent-orchestration` repo plans to use Companies House accounts that name directors (its `CLAUDE.md` describes a human-verified dataset from scanned accounts). It needs its own record of processing. Do not reuse this one.

## 2. Record of processing (Art. 30 style)

A small controller may be exempt from a full Art. 30 record, but processing that is not occasional removes the exemption. A short record is cheap and useful. This one is in the style of Art. 30.

| Activity | Personal data | Data subjects | Purpose | Lawful basis (Art. 6) | Retention | Recipients | Transfers |
|---|---|---|---|---|---|---|---|
| 1. 10-K corpus in the index | Names and public roles of directors and officers, signatures, compensation references, biographies ([data card, section 3](data-card.md)) | Executives and directors of Apple, Microsoft, J&J, Costco | Answer questions about public filings | Legitimate interest, Art. 6(1)(f). See the balancing test below | Until the index is deleted. Local DB kept until `docker compose down -v` ([data card, section 5](data-card.md)) | Neon (storage), model providers (chunk text at ingest, ZDR) | US providers, see section 4 |
| 2. Live question text | Whatever a visitor types. Not expected to be personal, but visitors could type some | Visitors | Embed, rerank and answer the question | Legitimate interest, Art. 6(1)(f) (no consent mechanism is planned) | Not stored by us. Not logged ([ADR 0021](../decisions/0021-deployment-hosting-logging-and-review-owners.md), `test_question_text_is_never_logged`). Providers: zero data retention requested on every call ([ADR 0009](../decisions/0009-models-and-privacy.md), control C16) | OpenRouter and the model providers | US providers, see section 4 |
| 3. Visitor IP addresses | IP address (online identifier) | Visitors | Per-IP rate limiting, abuse control | Legitimate interest, Art. 6(1)(f). See the balancing test below | In memory only, in a sliding window of up to one day ([`ratelimit.py`](../../src/multimodal_doc_rag/ratelimit.py): `DAY_S`, at most 10,000 addresses tracked). Lost on restart. Platform request logs: **unknown, to check** (Fly) | The process only. Fly sees the IP as the hosting platform | Fly's infrastructure location, `TODO(owner)` |

Not covered by the record because they do not happen:

- There is no user account, no cookie set by the API, and no stored question history.
- `/stats` holds counters only, never question text or IPs ([`stats.py`](../../src/multimodal_doc_rag/stats.py)).
- The one application log line on `/ask` carries latency, citation count and an idk flag ([`api.py`](../../src/multimodal_doc_rag/api.py)).

## 3. Legitimate interest balancing (short)

Three-part test: purpose, necessity, balance.

**Activity 1, public-role data in 10-Ks.**
- *Purpose:* a portfolio demo of document Q&A over public filings.
- *Necessity:* the filings name these people. Removing them would break the documents. The system does not profile, aggregate or extract data about individuals.
- *Balance:* the data is published by law for investors, and the filers are public-company officers. The effect on them is minimal. The system adds nothing new about them. Reasonable expectation: high. **Outcome:** likely passes. Revisit if someone objects, or if the system starts answering questions that profile named people.

**Activity 3, IP addresses in the rate limiter.**
- *Purpose:* stop scripted abuse and cap spend ([control matrix C26](control-matrix.md)).
- *Necessity:* a per-visitor limit needs some identifier. The IP is the least intrusive one available. It is held in memory only and not written to disk by our code.
- *Balance:* visitors would expect basic abuse protection on a public API. The impact is low and short-lived. **Outcome:** likely passes. The platform's own logs are the open question.

## 4. International transfers

Model providers and platforms are likely US-based or use US sub-processors. Transfers from the UK or EU need a valid mechanism. The usual routes are:

- the **UK International Data Transfer Agreement (IDTA)** or the **UK Addendum to the EU SCCs**, for UK exporters;
- the **EU Standard Contractual Clauses (SCCs)**, for EU exporters;
- the **EU-US Data Privacy Framework**, and the **UK Extension to it** (the UK-US data bridge), if the provider is certified.

| Provider | Mechanism | Status |
|---|---|---|
| OpenRouter | `TODO(owner)` | To verify |
| Model providers behind the ZDR endpoints | `TODO(owner)`, per provider | To verify |
| Fly.io | `TODO(owner)` | To verify |
| Neon | `TODO(owner)`. Holds public documents only, so low risk | To verify |

Region choice changes this. Deploying the app and database in a UK or EU region reduces the transfers to the model calls. `fly.toml` sets no region today, so it is an open item. Zero data retention ([ADR 0009](../decisions/0009-models-and-privacy.md)) lowers the risk of transferred question text, but does not remove the need for a mechanism.

## 5. Data subject rights

Rights: access, rectification, erasure, restriction, portability and objection (Arts. 15 to 21, check against source).

- **What exists to find:** nothing identifies a visitor in storage. Questions are not logged. IP counts are in memory and keyed by IP, with no link to any person.
- **How a request would be handled:**
  1. Acknowledge within the legal deadline (one month, extendable in some cases; check against source).
  2. For a visitor request: reply that question text is not stored, IP counts are in memory and expire within a day, and the owner cannot link either to a person. Art. 11 allows this answer where the controller cannot identify the person. Offer to check the platform's logs if the person gives the IP and a time window.
  3. For an executive or director named in a 10-K: the data is a public filing. For an objection (Art. 21) or erasure request, the owner can delete the relevant chunks from the index and record the decision. Assess each request on its facts.
- **Where requests go:** a contact address on the portfolio site, which the privacy notice must name. `TODO(owner)`.

## 6. DPIA screening

A DPIA (Art. 35) is needed where processing is likely to cause high risk. The ICO and the EU regulators publish criteria and lists (check against source). Screening against the common criteria:

| Criterion | This demo |
|---|---|
| Large-scale processing of special-category or criminal-offence data | No. Not expected in the corpus or questions |
| Systematic monitoring of people | No |
| Profiling or automated decisions with legal or similar effect | No. The system answers questions and takes no action |
| Vulnerable data subjects | No |
| Large scale | No. A demo with per-IP limits and a daily spend cap ([C26](control-matrix.md)) |
| Innovative technology | Yes, a generative model is used. Mitigated by zero data retention and no logging |
| Matching or combining datasets | No |

**Conclusion:** a full DPIA is likely not required. Record this screening. **Revisit if** question text starts to be logged, accounts or uploads are added, or user data is sent to a new provider.

## 7. Security of processing (Art. 32)

Existing controls, by link to the [control matrix](control-matrix.md). All deployment controls are planned until a deployment exists.

- Zero data retention and data-collection deny on every model request: C16 (implemented).
- Question text never logged: C20 (planned until deployed).
- Key kept as a `SecretStr`, never logged: C17 (implemented).
- Body size limit, security headers, bounded concurrency: C38 to C40 (planned until deployed).
- Read-only database role and non-root container: C31 (planned until deployed).
- Rate limits and spend cap: C26 (planned until deployed).
- Repository controls and secret scanning: C41, C42 (implemented).
- Incident handling and the 72-hour rule: [incident-response.md](incident-response.md).

## 8. Privacy notice (Art. 13)

**Required before deployment**, shipped with the AI notice (C15) on the portfolio site's ask page. It must say in plain words:

- who the controller is and how to contact them;
- what is processed: the question text (sent to model providers, not stored by us) and IP addresses (in memory for rate limiting, up to a day, plus platform logs);
- the purposes and the lawful basis (legitimate interest);
- the recipients: OpenRouter, the model providers, Fly.io;
- international transfers and the mechanism used;
- retention, as in section 2;
- the rights, and the right to complain to the ICO (and the visitor's own authority if in the EU);
- a warning not to type personal data into questions.

The README disclaimer ("Not financial, legal, or flight-training advice") is not a privacy notice.

## 9. Open items for the owner

- [ ] Choose the deploy region for Fly and Neon (UK, EU, or US). Not set in `fly.toml`.
- [ ] Get and file data processing terms (DPAs) for OpenRouter, Fly.io and Neon. For the model providers, confirm what OpenRouter's terms say about them.
- [ ] Find out how long Fly keeps request logs, and whether they hold IPs. Same for Neon logs. Not known from the repo.
- [ ] Write and publish the privacy notice (section 8), with C15.
- [ ] Confirm the transfer mechanism for each provider (section 4).
- [ ] Check whether an ICO data protection fee applies to the owner (check against source).
- [ ] Check whether an EU representative is needed under Art. 27 for EU visitors, or whether an exemption applies (check against source).
- [ ] Decide whether to accept the balancing tests in section 3.
- [ ] Start a separate record for `agent-orchestration` before it ingests Companies House data.
