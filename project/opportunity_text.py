"""Assembles reason / recommended_anchor_text / suggested_context.

These are template-generated from extracted page metadata -- Jev has no
free-text output (see jev_client.py), so it cannot produce these fields.
Every opportunity carries text_source="template" so this is never confused
with a model claim.
"""

from __future__ import annotations

from dataclasses import dataclass

from jev_client import PagePairJudgment

CONFIDENCE_THRESHOLDS = {"high": 0.75, "medium": 0.5}

REASON_TEMPLATES = {
    "supporting": "{target} provides supporting detail for a claim made in {source}.",
    "related": "{source} and {target} cover closely related topics with no existing link between them.",
    "parent_child": "{source} and {target} have a pillar/subtopic relationship.",
    "comparison": "{source} and {target} could be usefully cross-referenced as comparable options.",
}
DEFAULT_REASON_TEMPLATE = "{source} and {target} are topically related."


@dataclass
class LinkOpportunity:
    source_url: str
    source_title: str | None
    target_url: str
    target_title: str | None
    relationship_type: str
    relevance_score: float
    relevance_confidence: float
    confidence_label: str
    recommended_anchor_text: str
    suggested_context: str
    reason: str
    requires_editorial_review: bool
    text_source: str = "template"
    score_source: str = "jev"


def confidence_label(value: float) -> str:
    if value >= CONFIDENCE_THRESHOLDS["high"]:
        return "high"
    if value >= CONFIDENCE_THRESHOLDS["medium"]:
        return "medium"
    return "low"


def build_opportunity(
    judgment: PagePairJudgment,
    source_meta: dict,
    target_meta: dict,
    relevance_threshold: float = 0.5,
) -> LinkOpportunity | None:
    """Returns None when the pair doesn't clear the bar for a recommendation
    (not_relevant, or below relevance_threshold on the normalized 0-1 scale)."""
    if judgment.relationship_type == "not_relevant":
        return None
    if judgment.relevance_score_normalized < relevance_threshold:
        return None

    source_title = source_meta.get("title") or judgment.source_url
    target_title = target_meta.get("title") or judgment.target_url
    anchor = target_meta.get("h1") or target_meta.get("title") or target_title

    reason = REASON_TEMPLATES.get(judgment.relationship_type, DEFAULT_REASON_TEMPLATE).format(
        source=source_title, target=target_title
    )
    conf = confidence_label(min(judgment.relevance_confidence, judgment.relationship_confidence))

    return LinkOpportunity(
        source_url=judgment.source_url,
        source_title=source_meta.get("title"),
        target_url=judgment.target_url,
        target_title=target_meta.get("title"),
        relationship_type=judgment.relationship_type,
        relevance_score=judgment.relevance_score_normalized,
        relevance_confidence=judgment.relevance_confidence,
        confidence_label=conf,
        recommended_anchor_text=anchor,
        suggested_context=f"Add a contextual link to {target_title} where {source_title} discusses related content.",
        reason=reason,
        requires_editorial_review=(conf == "low"),
    )
