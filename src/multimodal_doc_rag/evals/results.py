"""Serializable per-question results and the whole-run report (what lands in reports/*.json)."""

from pydantic import BaseModel, ConfigDict, Field

from multimodal_doc_rag.contracts import Citation
from multimodal_doc_rag.evals.gold import GoldPage
from multimodal_doc_rag.evals.judge import JudgeVerdict
from multimodal_doc_rag.types import Passage


class RetrievedPassage(BaseModel):
    """One passage the generator saw. Page *idx* is what scoring uses; the labels are for
    humans. `content` is kept in full: error analysis and judge calibration (faithfulness)
    both need the text, and it makes a report self-contained."""

    chunk_id: int
    doc: str  # doc_key
    kind: str
    page_start_idx: int
    page_end_idx: int
    page_start_label: str | None
    page_end_label: str | None
    score: float
    content: str

    @classmethod
    def from_passage(cls, p: Passage) -> "RetrievedPassage":
        return cls(
            chunk_id=p.chunk_id,
            doc=p.doc_key,
            kind=p.kind,
            page_start_idx=p.page_start.idx,
            page_end_idx=p.page_end.idx,
            page_start_label=p.page_start.label,
            page_end_label=p.page_end.label,
            score=p.score,
            content=p.content,
        )


class ItemResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    corpus: str
    split: str
    type: str
    question: str
    answerable: bool
    reference_answer: str | None
    gold_pages: list[GoldPage]
    answer: str = ""  # as the API returns it: [k] = citations[k-1]
    # The text the judge graded: the model's own markers, [n] = retrieved[n-1]. Hand-graders
    # see this too, so judge and human grade the same string (calibration compares them).
    judged_answer: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    cited_chunk_ids: list[int] = Field(default_factory=list)
    retrieved: list[RetrievedPassage] = Field(default_factory=list)
    # name -> 0/1/fraction, or None when undefined for this item (e.g. recall on an
    # unanswerable question). Aggregation averages only the non-None values.
    metrics: dict[str, float | None] = Field(default_factory=dict)
    verdict: JudgeVerdict | None = None
    judge_error: str | None = None  # the judge failed or was cut off; rule metrics still stand
    cost_usd: float = 0.0  # answering only: embed + rerank + generate
    judge_cost_usd: float = 0.0
    latency_ms: float = 0.0  # pipeline time, judge excluded
    error: str | None = None  # a non-budget failure; the item then has no metrics


class InjectionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    question: str
    attack_goal: str
    canary: str | None
    answer: str = ""
    judged_answer: str | None = None  # see ItemResult.judged_answer
    retrieved: list[RetrievedPassage] = Field(default_factory=list)
    metrics: dict[str, float | None] = Field(default_factory=dict)
    verdict: JudgeVerdict | None = None
    judge_error: str | None = None
    cost_usd: float = 0.0
    judge_cost_usd: float = 0.0
    latency_ms: float = 0.0
    error: str | None = None


class RunConfig(BaseModel):
    """Everything needed to interpret (and repeat) a run."""

    label: str
    started_utc: str
    git_commit: str
    git_dirty: bool
    corpus: str  # "10k", "faa" or "all"
    split: str
    generator_model: str
    generator_reasoning: bool = False  # hidden reasoning on/off (ADR 0015)
    judge_model: str | None  # None = run with --no-judge
    embedding_model: str
    rerank_model: str | None  # None = reranking off
    top_k: int
    recall_k: int
    candidates: int
    budget_usd: float
    include_drafts: bool
    limit: int | None
    index: dict[str, str | int | float]  # size of the database queried, chunk length stats
    database: str  # database NAME only, never credentials


class EvalReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config: RunConfig
    truncated: bool = False  # the cost cap stopped the run early
    truncated_reason: str = ""
    meter_summary: str = ""
    items: list[ItemResult] = Field(default_factory=list)
    injection: list[InjectionResult] = Field(default_factory=list)
