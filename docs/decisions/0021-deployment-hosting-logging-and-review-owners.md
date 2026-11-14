# 0021. Deployment: Fly.io + Neon, no question logging; who reviews held-out and injection

- **Status:** Accepted
- **Date:** 2026-11-14
- **Refines:** 0003 (deployment shape), 0016 (live-ops governance, controls C20 and C26/C27), 0020 (review scope).

## Context
Deployment (build plan step 19) was waiting on four owner decisions: where to host, what to do with the text of visitors' questions, who reviews the held-out questions, and who reviews the prompt-injection attacks. The code itself is host-agnostic: rate limits, the daily spend cap, CORS, `/stats`, the Dockerfile, the read-only DB role and the CI release gate. Nothing ships before `release_check.py` passes (0016).

## Options considered
**Hosting** (the data is Postgres with pgvector, a few hundred MB including figure images, plus a small Python container)
- **Fly.io app + Neon Postgres.** The container can scale to zero, so cold starts take a few seconds. Neon is serverless Postgres with pgvector. Idle cost is low.
- **Render web service + Render Postgres.** One vendor. Free web services sleep.
- **Railway.** App and database in one project, with usage-based billing.

**Question text**
- **Never log it.** Only counts, latency, cost, error and "I don't know" rates.
- **Log it for 30 days, or for 7 days.** This makes failure analysis possible, but needs a privacy notice and enforced retention.

**Held-out review:** the owner, or Claude with an owner spot-check, or Claude alone.

**Injection review:** the owner item by item, or Claude with an owner spot-check, or Claude alone.

## Decision
- **Hosting:** Fly.io for the API container, Neon for Postgres + pgvector.
- **Question text is never logged.** No setting turns it on (`test_question_text_is_never_logged`). Logs and `/stats` carry counts, latency, spend, and error and "I don't know" rates only.
- **Held-out questions: the owner reviews every item.** The release decision therefore rests on a human-reviewed set, even though dev was reviewed by Claude (0020).
- **Injection attacks: Claude reviews, the owner spot-checks.** Each verified item is tagged in the review record.

## Why
- **Scale-to-zero.** A portfolio demo is idle almost all the time. Fly plus Neon keeps idle cost near zero, and the recorded run on the site covers cold starts.
- **Not logging text** removes the privacy risk (R8) and the need for a retention mechanism. The trade-off: real visitor questions can't be studied. Aggregate rates still show whether the demo is failing.
- **An owner-reviewed held-out set** keeps the human check where it matters most: the one run that decides release.
- **Injection items are attack prompts, not answer keys.** A model review is lower risk there, and the owner's spot-check still guards it.

## Consequences
- The deploy workflow's placeholder step becomes a `flyctl deploy` once a Fly app exists. The repository then needs `FLY_API_TOKEN` and `RELEASE_CHECK_DATABASE_URL` secrets. The latter is the Neon read-only role's URL.
- **Set `TRUSTED_PROXY_HOPS` for Fly's proxy.** Fly puts one proxy in front of the app, so the value should be 1. Confirm it against Fly's docs when deploying, or every visitor shares one rate-limit bucket.
- **The database moves by `pg_dump`/`pg_restore`** from the local Postgres 18 container to Neon, with no re-ingest and no model spend. Check that Neon offers a compatible Postgres version and pgvector at least 0.8 first.
- **Revisit hosting** if cold starts hurt the demo or if Neon's storage limits are hit.
