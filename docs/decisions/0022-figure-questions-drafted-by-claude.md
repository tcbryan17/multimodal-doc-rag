# 0022. The FAA figure questions are drafted by Claude and verified by the owner

- **Status:** Accepted
- **Date:** 2026-11-15
- **Amends:** 0011 and 0018, for the FAA dev figure questions only. Everything else in those records is unchanged, including the held-out review and the owner's calibration grades.

## Context
0011 and 0018 say the owner writes the FAA dev figure questions personally: 12 of the 60 FAA dev questions. The drafting model skips figures on purpose, so these are the only questions that test reading a value off a chart or table image. Fifteen candidate figures were picked, one per chunk, and saved as images in `private/figure-candidates/`. The owner then asked Claude Code (Opus 5.5) to draft a question and answer for all 15, and to show them on a page where the owner could confirm, edit or drop each one.

## Options considered
- **The owner writes them (the plan in 0011 and 0018).** This is the strongest provenance: a human chose what to ask and read the answer off the figure. It was also the last owner task blocking the figure smoke run.
- **Claude drafts them and the owner verifies each one (chosen).** It is faster, and the owner still looks at every figure and answer. The cost is that the question was chosen by a Claude model.
- **Claude drafts them and they are stored with origin `owner`.** Rejected: `owner_item` means "the author is the verifier", so this would misstate who wrote the items.

## Decision
- **How Claude drafted them.** Claude read every answer from the image itself, not from the stored vision descriptions. It searched the body text of every FAA document for each candidate answer. Where the text already gave a value (for example 2 G at a 60° bank, or 225 mph never-exceed speed), it asked about a value only the figure shows. It also avoided the worked examples the captions and text narrate.
- **Answer tolerance.** Answers read off a curve or dial state a tolerance in words, for example "within about two tenths of a G". `numeric_match` requires every digit in the reference to appear in the answer, so a range written in digits would fail every answer.
- **How they are stored.** Each item has `origin: llm_draft` and `status: verified`. Its `notes` start with `drafter=claude-opus-5-5, verifier=owner 2026-11-15 (ADR 0022)`. `source_excerpt` names the figure the question was written from.
- **What the owner decided.** The owner confirmed 13 and dropped 2: F05, a plain text table, and F12, whose reading code the body text explains. The owner confirmed F06's dial read (numerals every 20 kt), which Claude had marked uncertain. FAA dev therefore has 13 figure questions, not 12, and 59 verified items in all, not 60.

## Why
- **The owner made the call.** It unblocks the figure smoke run and the baseline the same day.
- **The owner still checked every figure and answer.** That is a real human check, but a weaker one than authorship. The owner judged answers that were put in front of them rather than choosing what to ask.

## Consequences
- **Same-family risk.** The figure references are Opus-drafted, and the default generator (Haiku 5.5) is also a Claude model. Questions a Claude model chose may suit Claude's way of reading charts. Only the judge (0014) is outside the family. Reports, the data card and the system card should say the figure questions were Claude-drafted and owner-verified.
- **Two stored figure descriptions are wrong.** At ingest, the vision model described F06's red line as 180–190 kt (the dial shows about 160) and F14's stall-speed increase at 60° as about 20% (the chart shows about 40%, on a left axis that is not linear). These items test whether the generator reads the image or trusts the description. They also give risk R5 (figure misreading) its first concrete examples.
- **The owner can upgrade any item** by rewriting it and changing the tag in `notes`.
