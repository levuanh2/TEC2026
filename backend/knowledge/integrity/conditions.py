"""RAG V1.5 M5 follow-up: deterministic condition tags for claims, and the numeric comparison of
claims with the human-verified reference registry (docs/rag/RAG_V15_M5_CONDITION_TAGS.md).

A condition tag is emitted ONLY when the claim's own sentence states it in words this module knows
(exact cue match on the diacritic-folded text, never a guess). Every tag carries the span of the
words that state it. A cue that is negated ("không phải đất phèn") gives no tag. Nothing is inferred
from the document's title, source, publisher or neighbouring sentences.

Tags are `axis:value` (`reference_numeric.condition_axis`):

    baseline:continuous_flooding | baseline:conventional_practice | baseline:control
    quantity:ch4 | quantity:n2o | quantity:n2o_n              what the number is an amount of
    base:applied_n                                            the number is relative to applied nitrogen
    stage:<STAGES name>                                       crop growth stage (the M4 extractor's)
    period:season | period:year | period:day | period:winter_spring | period:summer_autumn
    soil:acid_sulfate | soil:alluvial | soil:saline
    variety:<code>                                            an explicit variety code ("giống OM5451")

Region is not a tag: it goes to ClaimValue.region (`mekong_delta`, `red_river_delta`).

The comparison is a non-blocking analysis aid. It never approves, rejects or quarantines, and a
mismatch is reported only against an entry a human has verified (reference_numeric.compare returns
`reference_unverified` otherwise). It reads only the claims it is given: no other tenant's data.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Mapping, Sequence

from knowledge.integrity import reference_numeric as rn
from knowledge.integrity.claims import STAGES, Claim, _cue, _fold, _sentences

CONDITION_EXTRACTOR_VERSION = "kn-conditions-1"

# axis:value -> cues (folded and matched as whole words; a trailing "*" is a word prefix)
CONDITION_CUES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("baseline:continuous_flooding", ("so với ngập liên tục", "so với ruộng ngập liên tục", "so với tưới ngập liên tục",
                                      "compared with continuous flooding", "compared to continuous flooding",
                                      "relative to continuous flooding", "versus continuous flooding")),
    ("baseline:conventional_practice", ("so với canh tác truyền thống", "so với tập quán canh tác",
                                        "so với cách làm truyền thống", "compared with conventional practice",
                                        "compared to conventional practice")),
    ("baseline:control", ("so với đối chứng", "so với ruộng đối chứng", "compared with the control",
                          "compared to the control")),
    ("quantity:n2o_n", ("n2o-n", "n2o - n", "n₂o-n")),
    ("quantity:n2o", ("n2o", "nitơ oxit", "nitrous oxide")),
    ("quantity:ch4", ("ch4", "mê-tan", "metan", "methane")),
    ("base:applied_n", ("lượng đạm bón", "lượng n bón", "đạm bón vào", "of applied nitrogen", "of the nitrogen applied",
                        "of nitrogen applied", "of applied n", "of n applied")),
    ("period:winter_spring", ("vụ đông xuân", "winter-spring season", "winter spring season")),
    ("period:summer_autumn", ("vụ hè thu", "summer-autumn season", "summer autumn season")),
    ("period:season", ("mỗi vụ", "trong vụ", "một vụ", "per season", "per crop season", "each season")),
    ("period:year", ("mỗi năm", "một năm", "per year", "per annum", "annually")),
    ("period:day", ("mỗi ngày", "per day", "daily")),
    ("soil:acid_sulfate", ("đất phèn", "acid sulfate soil*", "acid sulphate soil*")),
    ("soil:alluvial", ("đất phù sa", "alluvial soil*")),
    ("soil:saline", ("đất mặn", "đất nhiễm mặn", "saline soil*")),
)
REGION_CUES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("mekong_delta", ("đồng bằng sông cửu long", "đbscl", "mekong delta", "mekong river delta")),
    ("red_river_delta", ("đồng bằng sông hồng", "đbsh", "red river delta")),
)
# a more specific tag of the same span wins (n2o-n over n2o)
_SHADOWS = {"quantity:n2o": "quantity:n2o_n", "period:season": ("period:winter_spring", "period:summer_autumn")}
# a unit written with a period after a slash ("kg/ha/vụ", "kg CH4/ha/ngày"); folded text
_SLASH_PERIOD = re.compile(r"/\s?(vu|season|crop|nam|year|ngay|day)(?!\w)")
_SLASH_TAG = {"vu": "period:season", "season": "period:season", "crop": "period:season", "nam": "period:year",
              "year": "period:year", "ngay": "period:day", "day": "period:day"}
_VARIETY = re.compile(r"(?<!\w)(?:giong|variety|cultivar)\s+([a-z]{1,4}\s?-?\s?\d{2,5}[a-z]?)(?!\w)", re.IGNORECASE)
_NEGATION = re.compile(r"(?<!\w)(?:khong phai|khong|chang phai|chua|not|non|except|ngoai tru|tru)\s+(?:\w+\s+){0,2}$")
TAG_AXES = frozenset(rn.condition_axis(t) for t, _ in CONDITION_CUES) | {"stage", "variety"}


@dataclass(frozen=True)
class ConditionTag:
    tag: str
    start: int      # span in the (NFC) chunk content of the words stating the condition
    end: int
    text: str


@dataclass(frozen=True)
class ClaimConditions:
    claim_id: str
    tags: tuple[ConditionTag, ...]
    region: str | None
    region_evidence: ConditionTag | None
    extractor_version: str = CONDITION_EXTRACTOR_VERSION

    @property
    def tag_set(self) -> frozenset[str]:
        return frozenset(t.tag for t in self.tags)


def _sentence_of(content: str, claim: Claim) -> tuple[int, int]:
    for start, end in _sentences(content):
        if start <= claim.start < end:
            return start, end
    return 0, len(content)


def _negated(folded_lower: str, s_start: int, start: int) -> bool:
    return bool(_NEGATION.search(folded_lower[s_start:start]))


def _matches(folded_lower: str, s_start: int, s_end: int, cues: tuple[str, ...]):
    for cue in cues:
        for m in _cue(cue).finditer(folded_lower, s_start, s_end):
            if not _negated(folded_lower, s_start, m.start()):
                yield m.start(), m.end()


def condition_tags(claim: Claim, content: str) -> ClaimConditions:
    """The conditions the claim's own sentence states, each with its evidence span."""
    text = unicodedata.normalize("NFC", content)
    if text[claim.start:claim.end] != claim.text:
        raise ValueError(f"claim {claim.claim_id}: its span does not match the content it was extracted from")
    folded = _fold(text)
    lowered = folded.lower() if len(folded.lower()) == len(folded) else folded
    s_start, s_end = _sentence_of(text, claim)
    found: dict[str, ConditionTag] = {}
    for tag, cues in CONDITION_CUES:
        for start, end in _matches(lowered, s_start, s_end, cues):
            found.setdefault(tag, ConditionTag(tag, start, end, text[start:end]))
            break
    for m in _SLASH_PERIOD.finditer(lowered, s_start, s_end):
        tag = _SLASH_TAG[m.group(1)]
        found.setdefault(tag, ConditionTag(tag, m.start(), m.end(), text[m.start():m.end()]))
    for weaker, stronger in _SHADOWS.items():
        stronger = (stronger,) if isinstance(stronger, str) else stronger
        if weaker in found and any(s in found and found[s].start <= found[weaker].start < found[s].end
                                   for s in stronger):
            del found[weaker]
    if claim.stage:                                    # the M4 extractor's stage, from the same text
        cues = dict(STAGES)[claim.stage]
        for start, end in _matches(lowered, s_start, s_end, cues):
            found[f"stage:{claim.stage}"] = ConditionTag(f"stage:{claim.stage}", start, end, text[start:end])
            break
    for m in _VARIETY.finditer(lowered, s_start, s_end):
        if not _negated(lowered, s_start, m.start()):
            code = re.sub(r"[\s-]", "", m.group(1)).lower()
            found.setdefault(f"variety:{code}", ConditionTag(f"variety:{code}", m.start(), m.end(), text[m.start():m.end()]))
    region = evidence = None
    hits = [(start, name, end) for name, cues in REGION_CUES for start, end in _matches(lowered, s_start, s_end, cues)]
    if len({name for _, name, _ in hits}) == 1:      # two regions named: none is stated for this claim
        start, name, end = min(hits)
        region, evidence = name, ConditionTag(f"region:{name}", start, end, text[start:end])
    return ClaimConditions(claim.claim_id, tuple(sorted(found.values(), key=lambda t: (t.start, t.tag))), region, evidence)


def claim_value(claim: Claim, conditions: ClaimConditions) -> rn.ClaimValue | None:
    """The M5 comparison input for an extracted quantity claim, or None (nothing to compare)."""
    if claim.kind != "quantity" or claim.status != "extracted" or not claim.parameter or claim.value_min is None:
        return None
    try:
        low, high = Decimal(repr(claim.value_min)), Decimal(repr(claim.value_max))
    except InvalidOperation:
        return None
    return rn.ClaimValue(parameter=claim.parameter, unit=claim.unit, value_min=low, value_max=high,
                         conditions=conditions.tag_set, region=conditions.region)


@dataclass(frozen=True)
class NumericComparison:
    """One claim against one registry entry (or against none), with its full reasoning."""
    claim_id: str
    document_ref: str
    chunk_id: str
    claim_text: str
    parameter: str
    claim_unit: str
    claimed_min: str
    claimed_max: str
    conditions: tuple[ConditionTag, ...]
    region: str | None
    reference_id: str | None
    outcome: str                 # an rn.Outcome, or "no_reference"
    rationale: str
    conversion: str | None
    normalized_min: str | None
    normalized_max: str | None
    reference_unit: str | None
    reference_point: str | None
    reference_min: str | None
    reference_max: str | None
    source_url: str | None
    locator: Mapping[str, str | int] | None

    @property
    def is_mismatch(self) -> bool:
        return self.outcome in rn.MISMATCHES


def _s(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def compare_claims(claims: Sequence[Claim], contents: Mapping[tuple[str, str], str],
                   registry: rn.NumericRegistry) -> tuple[NumericComparison, ...]:
    """Every extracted quantity claim against every registry entry of its parameter. `contents` maps
    (document_ref, chunk_id) to the chunk text the claims were extracted from."""
    out: list[NumericComparison] = []
    for claim in claims:
        content = contents.get((claim.document_ref, claim.chunk_id))
        if content is None:
            continue
        conditions = condition_tags(claim, content)
        value = claim_value(claim, conditions)
        if value is None:
            continue
        base = dict(claim_id=claim.claim_id, document_ref=claim.document_ref, chunk_id=claim.chunk_id,
                    claim_text=claim.text, parameter=value.parameter, claim_unit=value.unit,
                    claimed_min=str(value.value_min), claimed_max=str(value.value_max), conditions=conditions.tags,
                    region=conditions.region)
        entries = [e for e in registry.entries if e.claim_parameter == value.parameter]
        if not entries:
            out.append(NumericComparison(**base, reference_id=None, outcome="no_reference",
                                         rationale="No registry entry compares this parameter: unresolved, not a mismatch.",
                                         conversion=None, normalized_min=None, normalized_max=None, reference_unit=None,
                                         reference_point=None, reference_min=None, reference_max=None, source_url=None,
                                         locator=None))
            continue
        for entry in entries:
            f = rn.compare(value, entry)
            out.append(NumericComparison(**base, reference_id=f.reference_id, outcome=f.outcome, rationale=f.rationale,
                                         conversion=f.conversion, normalized_min=_s(f.normalized_min),
                                         normalized_max=_s(f.normalized_max), reference_unit=f.reference_unit,
                                         reference_point=_s(f.reference_point), reference_min=_s(f.reference_min),
                                         reference_max=_s(f.reference_max), source_url=f.source_url,
                                         locator=dict(f.locator)))
    return tuple(sorted(out, key=lambda c: (c.document_ref, c.chunk_id, c.claim_id, c.reference_id or "")))
