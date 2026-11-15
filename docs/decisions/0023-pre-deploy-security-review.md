# 0023. Pre-deploy security review and hardening

- **Status:** Accepted
- **Date:** 2026-11-15
- **Builds on:** 0021 (Fly.io + Neon). Adds controls C38–C43 to the control matrix.

## Context
Both repositories are public, and the API is about to go live. Before deploying, the owner asked for a full security and hardening review of everything someone could target: secrets and personal data in git history, dependencies, the API, the container, the CI workflows, the GitHub settings and the site's ask UI.

**Checked and found sound:**
- **Secrets.** No secrets in either repository's history. The scan covered provider, cloud and GitHub key patterns, private keys and database URLs with passwords. The only committed password is the local development one, and its database listens on 127.0.0.1 only.
- **Dependencies.** `pip-audit` found no known vulnerabilities in the 173 locked Python packages.
- **API.** SQL is parameterised. Input is validated. `/stats` uses a constant-time token check. Provider errors return a generic 502. Question text is never logged. The rate limiter ignores forged `X-Forwarded-For` headers.
- **Container and database.** The container is non-root. The database role is read-only.
- **Deploy workflow.** It runs only when started by hand, and inputs reach the shell through environment variables.
- **Site ask UI.** It writes answers as text only, accepts only an https API, and allows the `?api=` override only on localhost.
- **Prompt.** Retrieved sources are fenced and citations validated.

**Gaps found:**
1. **The daily spend cap and the rate limits reset on every restart.** They live in memory, and Fly by default stops idle machines and starts them on the next request. So an abuser could spend the cap, wait for the machine to idle, and spend it again. The only backstop was the OpenRouter key, which also pays for ingest and evals.
2. **No request-body size limit.** A body is read into memory before the 1,000-character check rejects it.
3. **A few slow requests could block everyone.** Each `/ask` holds one of 4 database connections while the models answer, and a request waiting for a connection had no deadline.
4. **Interactive API docs (`/docs`, `/redoc`, `/openapi.json`) were public.** The API also sent no security headers.
5. **CI supply chain.** Actions were pinned to movable tags. The CI token's permissions relied on the repository default. Checkout left the token in `.git/config`.
6. **Repository settings.** There was no protection on `main`. Dependabot alerts were off. There was no channel for private vulnerability reports.
7. **The owner's personal email** was in `pyproject.toml`, and it is the author email on the existing commits.

## Options considered (for gap 1, the spend cap)
- **(a) A separate production key with its own small credit limit, plus one always-on machine (chosen).** Config only. The provider enforces the limit whatever the app's state, and draining or revoking the production key never touches ingest or evals.
- **(b) Persist spend in the database.** The cap would survive restarts. But the API's role is read-only by design (C31), so this needs a write grant on a new table, plus a migration.
- **(c) Both.** The strongest option, and the most work for a demo whose provider limit already bounds the loss.

## Decision
- **Gap 1 (option a).**
  - `fly.toml` keeps one machine running: `auto_stop_machines = "off"` and `min_machines_running = 1`.
  - Production gets its own OpenRouter key with its own credit limit (C43).
  - The runbook says not to scale past one machine.
- **Gap 2.** A plain ASGI middleware refuses bodies over `MAX_BODY_BYTES` (8 KB) with 413, before parsing. It refuses a body-carrying request with no `Content-Length` with 411 (C38).
- **Gap 3.**
  - The connection pool has a 5 s timeout. A request that can't get a connection gets 503 with `Retry-After`.
  - Fly holds requests past 8 per machine at its edge (C40).
- **Gap 4.**
  - The docs exist only when `API_DOCS=true`.
  - Every response carries `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, HSTS and a `default-src 'none'` CSP (C39).
- **Gap 5.**
  - Every action is pinned to a full commit SHA.
  - `ci.yml` declares a read-only token.
  - Checkout runs with `persist-credentials: false`.
  - Dependabot proposes weekly updates for Python, Actions and Docker (C41).
- **Gap 6.**
  - A ruleset on `main` in both repositories requires a pull request and blocks force pushes and deletion. On this repository it also requires the `check` CI job to pass. The site repository has no CI.
  - Dependabot alerts and security fixes are on.
  - Private vulnerability reporting is on, with `SECURITY.md` explaining it (C42).
- **Gap 7.**
  - The email is removed from `pyproject.toml`.
  - Local commits now use the GitHub noreply address.
  - History is not rewritten. The address is already public, and rewriting would break every clone and PR link.

## Why
Each fix closes a path that costs the owner money, availability or privacy, at low complexity. Every change except the GitHub settings is pinned by a test.

## Consequences
- **One machine, always on.** This costs a small fixed amount per month. It also means no horizontal scaling until the limiter and meter move to a shared store.
- **Clients must send `Content-Length`.** The site's `fetch` does. A hand-written chunked upload gets 411.
- **Changes to `main` must go through a pull request** that passes CI.
- **Still to do at deploy time (owner):**
  - create the production OpenRouter key and set its limit;
  - after the first deploy, confirm that the rate limit applies per visitor (`docs/deployment.md`);
  - in GitHub account settings, turn on "Block command line pushes that expose my email".
