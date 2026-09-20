"""Phase 3+: Jev (TypeSafe AI) integration for internal-link content analysis.

Verified against TypeSafe's official docs and the installed `typesafe-sdk`
0.7.0 package (its public API matches the docs exactly -- checked directly
against the installed classes, not just the docs text). Confirmed
capability boundaries that shape this module:

1. Jev does not fetch or browse URLs. `system_one(state, questions)` only
   evaluates a `state` (text, JSON object, or array) supplied by the
   caller. Page content is extracted by `page_fetch.py` before it ever
   reaches Jev.
2. Jev never generates free text. Every answer is one of:
     - Noul   -> NoulAnswer.noul: float in [0, 1]
     - Choice -> ChoiceAnswer.choice: str, .confidence: float, .probabilities: dict[str, float]
     - Score  -> ScoreAnswer.score: float (probability-weighted average
                 rubric index -- may fall between integer levels),
                 .confidence: float, .legend: dict[int, str], .probabilities: dict[int, float]
   There is no field for open-ended prose. "reason", "recommended_anchor_text",
   and "suggested_context" are assembled from extracted page metadata in
   `opportunity_text.py`, not by Jev, and are labeled accordingly.
3. One `system_one` call evaluates several named questions against ONE
   state, cheaply, in parallel. There is no documented multi-state batch
   call: analyzing many page pairs means one call per pair, run
   concurrently via `AsyncTypeSafeClient` with a bounded semaphore.
4. Documented rate-limit handling is `TypeSafeRateLimitError` (429) plus
   `RetryPolicy`, which already retries 408/429/5xx with backoff -- so this
   module leans on that rather than re-implementing retry logic. Pricing
   is not documented anywhere verified; each response's `usage` field
   (input/output token counts) is surfaced so real cost can be tracked
   empirically instead of estimated.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from typesafe_sdk import (
    AsyncTypeSafeClient,
    Choice,
    Score,
    TypeSafeAPIConnectionError,
    TypeSafeAPIError,
)

# Ordered weakest -> strongest. Index in this list is the rubric level Jev
# scores against; ScoreAnswer.score is a weighted average over these indices.
RELEVANCE_CRITERIA: list[str] = [
    "unrelated topics; a link here would confuse or mislead a reader",
    "loosely related; a link would not meaningfully help navigation",
    "clearly related topics that could support a contextual link",
    "target directly extends, defines, or is the practical next step "
    "for a concept discussed in the source content",
]

RELATIONSHIP_CRITERIA: dict[str, str] = {
    "supporting": "target provides deeper explanation or evidence for a claim made in source",
    "related": "same general topic, but no direct dependency between the two",
    "parent_child": "one page is a broader pillar/category and the other a specific subtopic of it",
    "comparison": "the pages compare alternatives, competitors, or options",
    "not_relevant": "no meaningful topical relationship",
}

MAX_CONTENT_CHARS = 3000  # cost containment: pricing is unverified, so keep state small


def _build_state(source: dict, target: dict) -> dict:
    """source/target: {"url", "title", "h1", "text"} from page_fetch.py."""
    return {
        "source_page": {
            "url": source["url"],
            "title": source.get("title"),
            "h1": source.get("h1"),
            "content": (source.get("text") or "")[:MAX_CONTENT_CHARS],
        },
        "target_page": {
            "url": target["url"],
            "title": target.get("title"),
            "h1": target.get("h1"),
            "content": (target.get("text") or "")[:MAX_CONTENT_CHARS],
        },
    }


@dataclass
class PagePairJudgment:
    source_url: str
    target_url: str
    relevance_score_raw: float          # weighted rubric index, e.g. 0.0-3.0
    relevance_score_normalized: float   # raw / (len(RELEVANCE_CRITERIA) - 1), in [0, 1]
    relevance_confidence: float
    relevance_legend: dict[int, str]
    relationship_type: str
    relationship_confidence: float
    relationship_probabilities: dict[str, float]
    model: str
    input_tokens: int | None
    output_tokens: int | None
    score_source: str = "jev"


@dataclass
class JevJudgmentError:
    source_url: str
    target_url: str
    error_type: str
    message: str
    status: int | None = None
    request_id: str | None = None


async def judge_page_pair(client: AsyncTypeSafeClient, source: dict, target: dict) -> PagePairJudgment:
    state = _build_state(source, target)
    result = await client.system_one(
        state=state,
        questions={
            "relevance": Score(
                instructions=(
                    "Rate how relevant target_page is as an internal link target "
                    "from within source_page's content, based on the topical "
                    "relationship between the two pages -- not on shared keywords."
                ),
                criteria=RELEVANCE_CRITERIA,
            ),
            "relationship": Choice(
                instructions="Classify target_page's relationship to source_page.",
                criteria=RELATIONSHIP_CRITERIA,
            ),
        },
    )

    relevance = result.scores["relevance"]
    relationship = result.choices["relationship"]
    rubric_max = len(RELEVANCE_CRITERIA) - 1

    return PagePairJudgment(
        source_url=source["url"],
        target_url=target["url"],
        relevance_score_raw=relevance.score,
        relevance_score_normalized=relevance.score / rubric_max if rubric_max else relevance.score,
        relevance_confidence=relevance.confidence,
        relevance_legend=dict(relevance.legend),
        relationship_type=relationship.choice,
        relationship_confidence=relationship.confidence,
        relationship_probabilities=dict(relationship.probabilities),
        model=result.model,
        input_tokens=result.usage.input_tokens,
        output_tokens=result.usage.output_tokens,
    )


async def judge_pairs(
    pairs: list[tuple[dict, dict]],
    api_key: str,
    base_url: str | None = None,
    model: str | None = None,
    concurrency: int = 5,
) -> list[PagePairJudgment | JevJudgmentError]:
    """Run judge_page_pair over many (source, target) pairs concurrently.

    A failure on one pair (rate limit exhausted, bad response, connection
    error) is captured as a JevJudgmentError rather than aborting the whole
    batch -- one bad page shouldn't lose every other result.
    """
    sem = asyncio.Semaphore(concurrency)

    async with AsyncTypeSafeClient(api_key=api_key, base_url=base_url, model=model) as client:

        async def _run(pair: tuple[dict, dict]) -> PagePairJudgment | JevJudgmentError:
            source, target = pair
            async with sem:
                try:
                    return await judge_page_pair(client, source, target)
                except TypeSafeAPIError as exc:
                    return JevJudgmentError(
                        source_url=source["url"],
                        target_url=target["url"],
                        error_type=type(exc).__name__,
                        message=str(exc),
                        status=exc.status,
                        request_id=exc.request_id,
                    )
                except TypeSafeAPIConnectionError as exc:
                    return JevJudgmentError(
                        source_url=source["url"],
                        target_url=target["url"],
                        error_type=type(exc).__name__,
                        message=str(exc),
                    )

        return await asyncio.gather(*(_run(p) for p in pairs))
