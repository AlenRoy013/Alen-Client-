import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jev_client import PagePairJudgment  # noqa: E402
from opportunity_text import build_opportunity, confidence_label  # noqa: E402


def make_judgment(relationship_type="supporting", relevance_normalized=0.8,
                   relevance_confidence=0.9, relationship_confidence=0.85) -> PagePairJudgment:
    return PagePairJudgment(
        source_url="https://example.com/a",
        target_url="https://example.com/b",
        relevance_score_raw=relevance_normalized * 3,
        relevance_score_normalized=relevance_normalized,
        relevance_confidence=relevance_confidence,
        relevance_legend={0: "x", 1: "y", 2: "z", 3: "w"},
        relationship_type=relationship_type,
        relationship_confidence=relationship_confidence,
        relationship_probabilities={"supporting": 0.85},
        model="jev-latest",
        input_tokens=100,
        output_tokens=0,
    )


def test_confidence_label_thresholds():
    assert confidence_label(0.9) == "high"
    assert confidence_label(0.75) == "high"
    assert confidence_label(0.6) == "medium"
    assert confidence_label(0.5) == "medium"
    assert confidence_label(0.3) == "low"


def test_not_relevant_never_produces_an_opportunity():
    judgment = make_judgment(relationship_type="not_relevant", relevance_normalized=0.9)
    assert build_opportunity(judgment, {}, {}) is None


def test_below_threshold_relevance_is_dropped():
    judgment = make_judgment(relevance_normalized=0.3)
    assert build_opportunity(judgment, {}, {}, relevance_threshold=0.5) is None


def test_opportunity_fields_and_low_confidence_flags_review():
    judgment = make_judgment(relevance_confidence=0.4, relationship_confidence=0.9)
    source_meta = {"title": "Commission Calc"}
    target_meta = {"title": "Commission Software", "h1": "Sales Commission Software"}

    opp = build_opportunity(judgment, source_meta, target_meta)

    assert opp is not None
    assert opp.recommended_anchor_text == "Sales Commission Software"
    assert "Commission Calc" in opp.reason
    assert "Commission Software" in opp.reason
    assert opp.confidence_label == "low"  # min(0.4, 0.9) -> low
    assert opp.requires_editorial_review is True
    assert opp.text_source == "template"
    assert opp.score_source == "jev"


def test_anchor_falls_back_to_title_then_url_when_no_h1():
    judgment = make_judgment()
    opp = build_opportunity(judgment, {}, {})
    assert opp.recommended_anchor_text == "https://example.com/b"
