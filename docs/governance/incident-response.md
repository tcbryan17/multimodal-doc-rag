# Incident response (skeleton)

Draft for owner review (2026-11-26)

This extends the short section "Monitoring and incident response (C27)" in [docs/deployment.md](../deployment.md), which stays the source for the spend cut-off steps. Nothing is deployed yet, so no step below has been run on a live system. All kill switches in the table are planned until a deployment exists ([control matrix](control-matrix.md)).

## 1. Severity levels

| Level | Meaning | Examples | Target response |
|---|---|---|---|
| S1 | Harm outside the demo, or money leaving fast | Personal data exposed (a leaked secret, a database dump, logs that hold question text). Cost runaway: spend rising past the daily cap or a drained provider key. A prompt injection that gets the system to leak a secret or produce output the site renders unsafely | Act at once. Cut spend or take the service down first, then investigate |
| S2 | The control worked but a bypass was shown, or quality is broken | A successful injection with no leak (the canary appears, [C4](control-matrix.md)). Rate limit bypass. Sustained 502 or 503. "I don't know" rate collapses or falls to near zero ([deployment.md](../deployment.md)) | Same day |
| S3 | Wrong or low-quality answers | A visitor reports a wrong answer, a wrong figure or a bad citation. A caption-only figure is hit. Cosmetic UI faults | Within a week. Log in the risk register if it repeats |

Names are suggestions. `TODO(owner)`: adjust the examples and the target times to what you can really do.

## 2. Kill switches that exist

| Switch | What it does | Where | Status |
|---|---|---|---|
| Daily spend cap | `DailyCostMeter` stops `/ask` for the rest of the UTC day once spend reaches `DAILY_SPEND_CAP_USD` (default 1.0). The API answers 503. | [`spend.py`](../../src/multimodal_doc_rag/spend.py), `settings.daily_spend_cap_usd` | Code ready, planned until deployed (C26). In memory, resets on restart |
| Per-IP rate limits | 429 past `RATE_LIMIT_PER_MINUTE` and `RATE_LIMIT_PER_DAY` | [`ratelimit.py`](../../src/multimodal_doc_rag/ratelimit.py) | Code ready, planned until deployed (C26) |
| Disable or rotate the production OpenRouter key | Stops all model spend within seconds. `/ask` then answers 503 | OpenRouter dashboard ([deployment.md](../deployment.md)) | Planned. The production key does not exist yet (C43) |
| Provider credit limit | Hard ceiling on spend whatever the app does | OpenRouter dashboard (C22, C43) | C22 implemented for the current key. The production key is planned |
| Scale the service to zero, or stop it | Takes the API offline | Fly dashboard ([deployment.md](../deployment.md)) | Planned |
| Tighten limits and cap | Lower `RATE_LIMIT_*` and `DAILY_SPEND_CAP_USD` before restoring service | Host configuration | Planned |

Important: `fly.toml` keeps one machine always on, so scaling to zero is a deliberate manual step ([C43](control-matrix.md)).

## 3. Steps

1. **Notice.** Sources: the owner's daily check of OpenRouter spend, `GET /stats` (requests, errors, "I don't know" answers, latency, today's spend), host health and restart counts, a visitor report, a GitHub private vulnerability report ([SECURITY.md](../../SECURITY.md)). Question text is never logged ([ADR 0021](../decisions/0021-deployment-hosting-logging-and-review-owners.md)), so you cannot find a bad question in logs.
2. **Triage.** Set a severity. Write the time and what you saw in a short incident note (section 5).
3. **Contain.** For S1, use the kill switches above in the order in [deployment.md](../deployment.md): disable the production key, then scale to zero, then lower the credit limit. Rotate any secret that may have been exposed.
4. **Assess personal data.** If personal data may be involved, decide whether this is a personal data breach (section 4). Question text is not stored, so the likely exposures are IPs in platform logs or a leaked credential.
5. **Fix.** Find the cause. Add a test that would have caught it. Update the control matrix and the risk register if a risk became real.
6. **Restore.** Create a new key only after the cause is understood. Re-check rate limiting per visitor ([deployment.md](../deployment.md)).
7. **Review.** Section 5.

## 4. Who is told

- **The owner** is the only responder. There is no one else to page.
- **ICO.** Under UK GDPR Art. 33, a personal data breach must be reported to the ICO within 72 hours of becoming aware, unless it is unlikely to result in a risk to people (check against source). Record every breach, reported or not.
- **Affected people.** Art. 34 requires telling people directly where the risk to them is high (check against source).
- **EU authority.** If EU GDPR also applies and the breach affects EU visitors, check whether a report to an EU authority is needed (check against source). See [gdpr.md](gdpr.md).
- **Providers.** Tell OpenRouter, Fly.io or Neon if the incident involves their service. Contacts are below.
- **Visitors.** For S1 or S2, a short notice on the portfolio site. `TODO(owner)`: decide where.
- **Security reporters.** Reply through the GitHub advisory thread. [SECURITY.md](../../SECURITY.md) aims to acknowledge within a week.

## 5. Post-incident review

Within a week of closing an incident, write a short note under `docs/governance/` (as [deployment.md](../deployment.md) says). It covers:

- what happened, and when;
- how it was noticed, and how long it took;
- what was done, and what it cost;
- the cause;
- what changes (a test, a control, a setting);
- risk register rows to update.

If a decision changes, write a new ADR. Never edit an accepted one.

## 6. Provider contacts (placeholders)

| Provider | Support or security contact | Notes |
|---|---|---|
| OpenRouter | `TODO(owner)` | Dashboard for the key and credit limit |
| Fly.io | `TODO(owner)` | |
| Neon | `TODO(owner)` | |
| GitHub | `TODO(owner)` | Private vulnerability reporting is on ([C42](control-matrix.md)) |
| ICO | `TODO(owner)`: breach reporting route | |
| Owner contact for reporters | `TODO(owner)` | |
