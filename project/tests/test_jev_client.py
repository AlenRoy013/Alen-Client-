import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from typesafe_sdk import (
    ChoiceAnswer,
    ScoreAnswer,
    SystemOneResponse,
    TypeSafeAPIError,
    TypeSafeRateLimitError,
    Usage,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jev_client import (  # noqa: E402
    RELEVANCE_CRITERIA,
    JevJudgmentError,
    PagePairJudgment,
    judge_page_pair,
    judge_pairs,
)

SOURCE = {"url": "https://example.com/blog/sales-commission-calculation", "title": "Commission Calc", "text": "..."}
TARGET = {"url": "https://example.com/sales-commission-software", "title": "Commission Software", "text": "..."}


def make_response(score: float, confidence: float, choice: str) -> SystemOneResponse:
    return SystemOneResponse(
        model="jev-latest",
        usage=Usage(input_tokens=120, output_tokens=0),
        answers={
            "relevance": ScoreAnswer(
                type="score",
                score=score,
                confidence=confidence,
                legend={i: c for i, c in enumerate(RELEVANCE_CRITERIA)},
                probabilities={0: 0.05, 1: 0.1, 2: 0.2, 3: 0.65},
            ),
            "relationship": ChoiceAnswer(
                type="choice",
                choice=choice,
                confidence=0.82,
                probabilities={"supporting": 0.82, "related": 0.1, "parent_child": 0.03, "comparison": 0.03, "not_relevant": 0.02},
            ),
        },
    )


@pytest.mark.asyncio
async def test_judge_page_pair_normalizes_score_and_extracts_fields():
    fake_client = AsyncMock()
    fake_client.system_one.return_value = make_response(score=2.4, confidence=0.78, choice="supporting")

    result = await judge_page_pair(fake_client, SOURCE, TARGET)

    assert isinstance(result, PagePairJudgment)
    assert result.source_url == SOURCE["url"]
    assert result.target_url == TARGET["url"]
    assert result.relevance_score_raw == 2.4
    assert result.relevance_score_normalized == pytest.approx(2.4 / 3)
    assert result.relationship_type == "supporting"
    assert result.relationship_confidence == 0.82
    assert result.input_tokens == 120
    assert result.score_source == "jev"


@pytest.mark.asyncio
async def test_judge_page_pair_sends_state_without_fetching_urls_itself():
    fake_client = AsyncMock()
    fake_client.system_one.return_value = make_response(score=0.0, confidence=0.9, choice="not_relevant")

    await judge_page_pair(fake_client, SOURCE, TARGET)

    call_kwargs = fake_client.system_one.call_args.kwargs
    state = call_kwargs["state"]
    assert state["source_page"]["url"] == SOURCE["url"]
    assert state["target_page"]["url"] == TARGET["url"]
    assert set(call_kwargs["questions"].keys()) == {"relevance", "relationship"}


@pytest.mark.asyncio
async def test_judge_pairs_captures_per_pair_api_errors_without_aborting_batch():
    good_response = make_response(score=3.0, confidence=0.9, choice="supporting")

    async def fake_system_one(**kwargs):
        if kwargs["state"]["target_page"]["url"] == "https://example.com/broken":
            raise TypeSafeAPIError(status=500, body=None, headers={}, endpoint="POST /v1/system-one")
        return good_response

    with patch("jev_client.AsyncTypeSafeClient") as MockClient:
        instance = AsyncMock()
        instance.system_one.side_effect = fake_system_one
        instance.__aenter__.return_value = instance
        MockClient.return_value = instance

        pairs = [
            (SOURCE, TARGET),
            (SOURCE, {"url": "https://example.com/broken", "title": "x", "text": "x"}),
        ]
        results = await judge_pairs(pairs, api_key="dummy", concurrency=2)

    assert len(results) == 2
    oks = [r for r in results if isinstance(r, PagePairJudgment)]
    errors = [r for r in results if isinstance(r, JevJudgmentError)]
    assert len(oks) == 1
    assert len(errors) == 1
    assert errors[0].target_url == "https://example.com/broken"
    assert errors[0].error_type == "TypeSafeAPIError"


@pytest.mark.asyncio
async def test_rate_limit_error_is_captured_as_judgment_error_not_raised():
    with patch("jev_client.AsyncTypeSafeClient") as MockClient:
        instance = AsyncMock()
        instance.system_one.side_effect = TypeSafeRateLimitError(
            status=429, body=None, headers={}, endpoint="POST /v1/system-one"
        )
        instance.__aenter__.return_value = instance
        MockClient.return_value = instance

        results = await judge_pairs([(SOURCE, TARGET)], api_key="dummy")

    assert len(results) == 1
    assert isinstance(results[0], JevJudgmentError)
    assert results[0].status == 429
