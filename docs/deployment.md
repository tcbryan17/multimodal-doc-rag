# Deployment

Nothing is deployed yet. This page lists what is already built, what is left, and the order
to do it in. **Hosting is the owner's decision** and nothing here is tied to a host.

## What exists (scaffolding on branch `deploy-ops-scaffolding`)

| Piece | File | Control |
|---|---|---|
| API container image: multi-stage, pinned base, runs as a non-root user, `HEALTHCHECK` on `/health`, listens on `$PORT` (default 8000) | `Dockerfile`, `.dockerignore` | C31 |
| Read-only database role (SELECT on `documents`, `chunks`, `embeddings`, `figures` only) | `docker/roles/readonly_role.sql`, `tests/test_readonly_role.py` | C31 |
| Manual deploy gate: full checks, then `release_check.py`, then a disabled deploy placeholder | `.github/workflows/deploy.yml`, `tests/test_deploy_workflow.py` | C37 |
| This runbook, including monitoring and incident response | `docs/deployment.md` | C27 |

All of these stay **planned** in the [control matrix](governance/control-matrix.md) until a
real deployment exists and has been checked.

### Docker in five lines

- An **image** is a frozen filesystem plus a start command; a **container** is a running copy.
- The `Dockerfile` has two stages: a *builder* installs dependencies with `uv`, and the final
  stage copies only the finished virtualenv. Smaller, and no build tools to attack.
- `.dockerignore` keeps `.env*`, `data/`, `private/`, `evals/` and `reports/` out of the image.
- Config and secrets are passed as **environment variables at run time**, never baked in.
- The container runs as user `app` (uid 10001), not root.

Try it locally (needs OrbStack running and the compose database up):

```bash
docker build -t mdr-api:test .
# Inside a container "localhost" is the container itself, so reach the compose database via
# the host: host.docker.internal works on OrbStack and Docker Desktop.
docker run --rm -p 8000:8000 \
  -e DATABASE_URL=postgresql://rag:rag-dev-only@host.docker.internal:5433/rag \
  mdr-api:test
curl localhost:8000/health        # {"status":"ok"}
```

## What is left, in order

1. **Choose the hosts (owner).** You need somewhere to run the container and a managed
   Postgres with the `vector` extension (pgvector). Questions to weigh: free tier or
   scale-to-zero (cost and cold starts), whether the host offers a secret store and
   per-IP rate limiting, and whether the CI runner can reach the database (needed by the
   release check, step 6). Record the choice as an ADR in `docs/decisions/` (rejected options
   included), as CLAUDE.md requires for architectural choices.
2. **Create the production database and load the index** (next section). The corpus is
   already ingested locally, so you copy it. You do not re-ingest or spend model credit.
3. **Create the read-only role** and build the API's connection string from it.
4. **Put secrets in the host's secret store.**
5. **Set the CORS origin** for the portfolio site.
6. **Run the release check** through the deploy workflow. It must pass.
7. Replace the placeholder step in `deploy.yml` with the host's deploy command, deploy, then
   set up monitoring (C27) before announcing the URL.

Not built yet and tracked in the matrix: per-IP rate limits and a daily spend cap (C26),
the question-logging policy (C20, below), the EU AI Act Art. 50 AI notice, and the UI
rendering answers as text.

## Copy the database from local to production

`pg_dump` writes the database to a file; `pg_restore` loads it elsewhere. This copies the
rows that already exist, embeddings included, so there are no model calls and no cost.

Use a `pg_dump` that matches the server's major version (the local server is Postgres 18;
a Homebrew `pg_dump` 14 will refuse). Running it inside the compose container guarantees a
match:

```bash
# 1. Dump the local database to a custom-format file (compressed, restorable selectively).
#    --no-owner/--no-acl: don't copy local user names or grants; the new server sets its own.
docker compose exec -T db pg_dump -U rag -d rag --format=custom --no-owner --no-acl > rag.dump

# 2. On the production server, enable pgvector once if the host does not do it for you:
psql "$PROD_ADMIN_URL" -c 'CREATE EXTENSION IF NOT EXISTS vector;'

# 3. Restore. --exit-on-error stops at the first problem instead of half-loading.
#    Use a pg_restore of version >= the dump's (e.g. from a postgres:18 container if needed).
pg_restore --no-owner --no-acl --exit-on-error -d "$PROD_ADMIN_URL" rag.dump

# 4. Sanity check: row counts match the local database.
psql "$PROD_ADMIN_URL" -c 'SELECT (SELECT count(*) FROM documents) d, (SELECT count(*) FROM chunks) c, (SELECT count(*) FROM embeddings) e, (SELECT count(*) FROM figures) f;'
```

The dump includes `schema_migrations`, so the restored database is already at the right
schema version; running `python -m multimodal_doc_rag.db.migrate` afterwards is a no-op.
The dump contains the whole corpus index (public documents only) and no secrets, but treat
`rag.dump` as large and delete it when done. The comparison databases (`rag_chunk<N>`,
`rag_eval`) are not needed in production.

## The read-only role

The API only reads. Create a role that can only read, so a bug or injection that reached SQL
cannot change data (control C31). Run once per database, as an admin, after the restore:

```bash
psql "$PROD_ADMIN_URL" \
  -v ro_password="$(openssl rand -base64 24 | tr -d '/+=')" \
  -f docker/roles/readonly_role.sql
```

The password is generated at run time and never committed. Copy it straight into the host's
secret store (below); you cannot read it back from Postgres. The role is named
`rag_readonly` (override with `-v ro_role=...`). It can `SELECT` from `documents`, `chunks`,
`embeddings` and `figures` and nothing else; `tests/test_readonly_role.py` proves it.

**How the API uses it:** the API reads one setting, `DATABASE_URL`. In production set it to
the read-only login, not the admin one:

```
DATABASE_URL=postgresql://rag_readonly:<password>@<prod-host>:5432/rag
```

Keep the admin/owner URL out of the running service. Use it only for restores, migrations
and ingest, from your machine. The same read-only URL also works as the CI secret
`RELEASE_CHECK_DATABASE_URL`, since the release check only reads figure counts.

If a future migration adds a table the API must read, add it to the `GRANT SELECT` line in
the script and re-run it (it is idempotent).

## Secrets

Set these in the host's **secret store** (or the platform's "environment variables"
screen marked secret), never in the repo, the image or a committed file:

| Variable | Value |
|---|---|
| `DATABASE_URL` | the read-only URL above |
| `OPENROUTER_API_KEY` | a project-only key with a low credit limit (C22). Use a **separate key for production** so it can be revoked without touching ingest and evals |

Other settings (model IDs, caps) have safe defaults in `config.py`; see `.env.example` for
the list. In GitHub, add `RELEASE_CHECK_DATABASE_URL` as a repository (or environment) secret
for the deploy workflow.

## CORS origin

Browsers only let the portfolio site call the API if the API allows that site's origin.
Allow exactly the site's origin (for example `https://<your-site-domain>`), not `*`. How the
API reads the allowed origin is being added in `api.py`/`config.py` separately; once that
lands, set the corresponding variable in the host's configuration and confirm with a browser
request from the real site.

## The release check gate

`.github/workflows/deploy.yml` is started by hand (**Actions > Deploy gate > Run workflow**)
and asks for the evidence: the held-out final report, the direct and indirect injection
reports, and the calibration name. It runs lint, types and tests, then
`scripts/release_check.py`. A non-zero exit (a failed gate or missing evidence) fails the
job, and the deploy step after it never runs. The verdict file is attached to the run as an
artifact. The deploy step itself is a disabled placeholder (`if: false`) with a comment at the
exact spot to add the host's deploy command. The check can only pass after the held-out final
run (build plan step 18).

## Monitoring and incident response (C27)

### What to watch

Check these daily at first (a host dashboard or a small script over logs/provider data):

- **Spend per day.** OpenRouter's activity page for the production key is the source of
  truth. Compare against the expected cost per question (gate: mean at most $0.005). A jump
  means abuse or a retry loop.
- **Error rate.** Share of `/ask` responses that are 5xx. 503 means the key is missing or
  disabled, 502 means the model provider failed (the API never returns a bare 500 by design).
  Sustained 502s usually mean the provider is down or the key hit its limit.
- **"I don't know" rate.** A sudden rise suggests retrieval is broken (wrong or empty
  database, missing embeddings); a sudden fall to near zero could mean the model is
  answering things it should refuse. Compare against the held-out run's rate.
- Host health: the container's `/health` check and restart counts.

### Cutting spend fast (in this order, stop when spend stops)

1. **Disable or rotate the production OpenRouter key** in the OpenRouter dashboard. This
   stops spending within seconds, whatever state the app is in; `/ask` then answers 503.
   Create a new key and update the host's secret only after the cause is understood.
2. **Scale the service to zero** (or stop it) in the host's dashboard.
3. Lower the key's credit limit to the amount you are willing to lose.
4. Once rate limits and a daily cap exist (C26), tighten them before turning things back on.

### Who to contact

The project owner (tcbryan17) is the only responder: GitHub issues on the repository, or the
contact on the owner's portfolio site. Record the host's and OpenRouter's support pages here
once they are chosen.

### After an incident

Write down what happened, how it was noticed, and what changed in a short note under
`docs/governance/` (and update the risk register if a risk was realised). Rotate any secret
that may have been exposed.

## Open decision (owner): question logging (C20)

Whether to log visitors' questions, for how long, and how to keep personal data out of logs
is **not decided**. Until the owner decides, the safe default is to not store question text
anywhere beyond what the host's own request logs keep, and to check what those retain. This
policy must be written down (control C20) before the public launch; it also affects what you
can monitor (the "I don't know" rate needs counts, not question text).
