# 0003. Docker Compose for local Postgres; replay-first, then a capped live demo

- **Status:** Accepted
- **Date:** 2026-11-07

## Context
We need Postgres with pgvector. The portfolio site can play back a recorded trace (`replay/sample-run.json`), but a live `/ask` endpoint shows more. The development machine has Homebrew `postgresql@14` and no container runtime.

## Options considered (database)
- **Docker Compose with the `pgvector/pgvector` image.** Pros: reviewers get an identical database with `docker compose up`, the same image can run in deployment, and container skills carry over to other work. Cons: needs a container runtime (a VM on macOS).
- **Homebrew Postgres.** Pros: native and lightweight. Cons: tied to one machine, the installed version (14) is old, and compatibility with pgvector is unverified.
- **Hosted Postgres (Neon or Supabase).** Pros: no local setup, free tiers support pgvector, and it can double as the production database. Cons: needs internet, and free tiers pause when idle.

## Options considered (demo)
- **Replay only.** Free and can't be abused, but it's a recording, not a working system.
- **Live endpoint.** More convincing, but costs money and can be abused.

## Decision
- Local development runs Postgres and pgvector in Docker Compose.
- Build against replay first. Once eval numbers are good, add a live `/ask` with a capped OpenRouter key (see 0002), per-IP rate limiting, and limits on input and output size.
- The production database host is still undecided; hosted Neon is the current front-runner. It's the same extension, so switching only changes the connection string.

## Consequences
- The container runtime (OrbStack or Docker Desktop) is the developer's choice. The Compose file works with either.
- The live endpoint needs the security work listed in 0002 (rate limiting, a read-only database role, a non-root container) before launch.
