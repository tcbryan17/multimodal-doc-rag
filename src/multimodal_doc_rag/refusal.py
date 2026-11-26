"""Refusal policy: when should the system say "I don't know" instead of answering?

Status quo (ADR 0005, 0009): refusal is prompt-only. `answer.SYSTEM_PROMPT` rule 3 tells the
model to reply with exactly `IDK` when the sources lack the answer. `pipeline.py` returns IDK
by itself only when retrieval found no passages at all. So a weak but non-empty retrieval is
left to the model's judgement, and models are known to answer anyway.

Options:
(a) Prompt-only (status quo). Zero code and one model call. But the refusal is only as good
    as the model's self-assessment, and an injected source can talk it out of refusing.
(b) Reranker-score floor before the model call. If the best reranker score is below a
    threshold, skip generation and return IDK. Why it works: the reranker scores how well a
    passage answers the question, so a low top score means retrieval found nothing relevant.
    It also saves the generation cost. Costs: the threshold must be tuned, and the reranker
    fallback path (ADR 0009, hybrid RRF order) has no comparable scores, so the floor cannot
    apply there. RRF scores are on a different scale and must never be compared to it.
(c) Post-hoc check: an answer with zero valid citations means IDK. Why it works: the prompt
    demands a citation for every claim, and `parse_citations` drops markers that do not match
    a provided passage. An answer that survives with no citation is unsupported by
    construction. Costs: the generation call is already paid, and a correct IDK has no
    citations either, so only non-IDK text with no citations should be turned into IDK.
(d) Both b and c. Cheap early exit for clearly irrelevant retrieval, plus a safety net for
    uncited answers. Two things to tune and explain instead of one.

Measurement. Two pre-registered gates in `evals/gates.toml` measure the choice:
`abstention` (unanswerable questions where the system declined, >= 0.80, pooled) and
`false_abstention` (answerable questions where it declined, <= 0.10, per corpus). They pull
in opposite directions: a higher floor raises abstention and also false abstention.

Tuning rule. Pick any threshold on the DEV set only, never on held-out (ADR 0011, 0016).
The gates are frozen once the dev baseline exists, so tune before that or write a superseding
ADR. Record the choice in a new ADR.

Wiring. This module is not imported anywhere yet. Wiring it into `pipeline.py` is a one-line
call that Toby adds himself.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from multimodal_doc_rag.types import Passage


@dataclass(frozen=True)
class RefusalDecision:
    refuse: bool
    reason: str  # short and stable, safe to log (never the question text, ADR 0021)


def decide_refusal(
    passages: Sequence[Passage],
    rerank_scores: Sequence[float] | None,
    answer_text: str | None,
    cited: Sequence[int],
) -> RefusalDecision:
    """Decide whether to refuse.

    passages: what the generator saw (or would see), best first.
    rerank_scores: one reranker score per passage, or None on the fallback path.
    answer_text: the generator's text, or None when deciding before the model call.
    cited: validated cited chunk ids (a subset of the passages' chunk ids).
    """
    # TODO(human): implement your chosen option (a, b, c or d) from the module docstring.
    raise NotImplementedError("TODO(human): choose refusal option and return a RefusalDecision")
