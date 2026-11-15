# Security policy

## Reporting a vulnerability

Please report security issues **privately** through GitHub: open the repository's
**Security** tab and choose **Report a vulnerability**. Don't open a public issue for a
security problem.

I aim to acknowledge reports within a week. This is a one-person portfolio project, so
there is no bug bounty.

## Scope

In scope:

- The API in `src/multimodal_doc_rag/` (`/ask`, `/figures`, `/stats`, `/health`) and its
  deployment configuration (`Dockerfile`, `fly.toml`, `.github/workflows/`).
- Prompt injection that makes the live `/ask` endpoint ignore its rules, leak its instructions,
  or produce output the portfolio site would render unsafely.
- Anything that lets a client get around the per-IP rate limit, the daily spend cap or the
  request size limits.

Out of scope:

- The source documents. They are public SEC filings and an FAA handbook.
- Denial of service by sheer volume. The demo has a deliberately small daily budget and
  answers 503 when it is spent.
- Findings that need access to the owner's machine or accounts.

## What is already in place

The controls, and the tests that prove them, are listed in
[`docs/governance/control-matrix.md`](docs/governance/control-matrix.md). The pre-deploy
review is recorded in [ADR 0023](docs/decisions/0023-pre-deploy-security-review.md).
