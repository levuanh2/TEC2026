"""M5 foundation: numeric reference entries (schema "kn-reference-registry-2"), a closed unit and
dimension model, a closed table of conversion rules, and the comparison of one claimed value with
one reference entry. Pure: stdlib only, no file, database or network access.

REVIEW AID ONLY. A finding never changes a knowledge status, blocks an approval or quarantines.

What this module refuses to do
  * invent a value, unit, range or tolerance: every number is a decimal string copied from the
    source, the unit as printed is kept next to the canonical one, and the only tolerances are the
    range the source prints or none;
  * compare across dimensions: a claim is compared with an entry only through a NAMED rule of
    CONVERSION_RULES whose source and target dimensions are fixed and whose preconditions the claim
    states. No rule, no comparison ("not_comparable"). There is no generic ratio conversion;
  * give a dimensionless factor (a scaling or conversion factor) a made-up unit: such an entry has
    unit null, says what it is a ratio OF and relative TO, and can only use the rule "none";
  * use an entry no human has verified: it loads, so that a human can find what to check, and every
    comparison with it answers "reference_unverified", never a mismatch;
  * load an entry whose redistribution rights are not cleared.

The loader cannot know that the named human really did the check, or that the evidence file says
what the entry says. That is a review responsibility (CODEOWNERS on the registry file and on
docs/rag/reference-evidence/).

Document format:
{"schema": "kn-reference-registry-2", "registry_version": "<token>", "entries": [<entry>, ...]}
An empty entries list is valid: the committed registry holds no numeric entry until one is verified.
See docs/rag/RAG_V15_M5_REFERENCE_REGISTRY_FOUNDATION.md for the entry fields.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal

from knowledge.integrity.claims import PARAMETERS, UNITS
from knowledge.integrity.references import RegistryError, registry_digest

NUMERIC_REGISTRY_SCHEMA = "kn-reference-registry-2"
EVIDENCE_DIR = "docs/rag/reference-evidence/"

# ------------------------------------------------------------------ units and dimensions (closed)

# Canonical unit -> dimension. The claim units of M4 keep their dimension; the units below them are
# reference-only (no current claim carries them). A unit names what is measured: two units with the
# same arithmetic shape (a mass per mass, a percent) are different dimensions unless a rule says
# otherwise.
REFERENCE_UNITS: dict[str, str] = {
    **UNITS,
    # nitrogen emitted as N2O per nitrogen applied (IPCC EF1 family): a mass fraction of applied N
    "kgN2O-N/kgN": "n2o_n_per_applied_n",
}
DIMENSIONS = frozenset(REFERENCE_UNITS.values())

# What a number is. A scaling factor is an emission relative to a named reference condition; a
# conversion factor is a relative effect used inside a formula. Neither has a unit.
SEMANTIC_KINDS = frozenset({"emission_factor", "quantity", "scaling_factor", "conversion_factor"})
UNITLESS_KINDS = frozenset({"scaling_factor", "conversion_factor"})


@dataclass(frozen=True)
class ConversionRule:
    """claim value x factor = a value in the reference unit. Valid only for exactly this pair of
    units and only when the claim states every precondition."""
    name: str
    claim_unit: str | None            # None: the same unit as the reference (identity)
    reference_unit: str | None
    factor: Decimal
    preconditions: frozenset[str]     # condition tags the claim itself must carry
    rationale: str


# Adding a rule is a code change with its own review and its own test.
CONVERSION_RULES: dict[str, ConversionRule] = {
    "identity": ConversionRule(
        "identity", None, None, Decimal(1), frozenset(),
        "Same parameter and same canonical unit: the claimed number is compared as written."),
    "percent_of_applied_n_to_fraction": ConversionRule(
        "percent_of_applied_n_to_fraction", "percent", "kgN2O-N/kgN", Decimal("0.01"),
        frozenset({"base:applied_n", "quantity:n2o_n"}),
        "A percent of applied nitrogen emitted as N2O-N is that mass fraction times 100. Valid only when the "
        "claim names applied N as the base and N2O-N (not N2O mass) as the quantity."),
}
NO_CONVERSION = "none"                # stored for reference; never compared

RIGHTS_STATUSES = frozenset({"cleared", "not_cleared"})
HUMAN_STATUSES = frozenset({"pending", "verified"})
TOLERANCE_MODES = frozenset({"printed_range", "exact"})

Outcome = Literal["within_printed_range", "outside_printed_range", "equal_to_printed_value",
                  "differs_from_printed_value", "out_of_scope", "not_comparable", "reference_unverified"]
MISMATCHES = frozenset({"outside_printed_range", "differs_from_printed_value"})

_REF_ID = re.compile(r"^ref-[a-z0-9][a-z0-9-]{1,62}$")
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DECIMAL = re.compile(r"^-?\d+(\.\d+)?$")
_HTTPS = re.compile(r"^https://[^\s/]+/\S*$")
_TAG = re.compile(r"^[a-z0-9][a-z0-9_.:<>=-]{0,79}$")
_AXIS = re.compile(r"^[a-z0-9][a-z0-9_]{0,39}$")


def condition_axis(tag: str) -> str:
    """The axis of a condition tag: 'stage:tillering' -> 'stage'; a tag without ':' is its own axis."""
    return tag.split(":", 1)[0]


_EVIDENCE_REF = re.compile(r"^docs/rag/reference-evidence/[A-Za-z0-9][A-Za-z0-9._-]{0,99}\.md$")


@dataclass(frozen=True)
class NumericSource:
    title: str
    publisher: str
    edition: str
    effective_date: str | None        # ISO date the edition took effect, or None with a stated reason
    effective_date_note: str | None
    url: str
    artifact_sha256: str
    artifact_bytes: int
    locator: dict[str, str | int]     # table / equation, pdf_page, printed_page, section, row


@dataclass(frozen=True)
class NumericReference:
    reference_id: str
    parameter: str
    point: Decimal
    range_min: Decimal | None
    range_max: Decimal | None
    range_basis: str | None
    unit_as_printed: str
    unit: str | None
    dimension: str | None
    semantic_kind: str
    relative_to: str | None
    numerator: str
    denominator: str
    conditions: tuple[str, ...]              # applicability, in the source's words
    region: str | None
    tier: str | None
    source: NumericSource
    rights_basis: str
    rights_reference: str
    rights_restrictions: str
    claim_parameter: str | None
    claim_unit: str | None
    conversion: str
    required_claim_conditions: frozenset[str]
    invariant_condition_axes: frozenset[str]   # axes on which the source says the value does not vary
    invariance_basis: str | None
    tolerance_mode: str
    machine_read: str
    human_status: str
    verified_by: str | None
    verified_at: str | None
    evidence_ref: str | None
    evidence_sha256: str | None
    limitations: tuple[str, ...]
    synthetic: bool = False

    @property
    def usable(self) -> bool:
        """Only an entry a named human verified against the hashed artifact is ever compared."""
        return self.human_status == "verified"


@dataclass(frozen=True)
class NumericRegistry:
    registry_version: str
    digest: str
    entries: tuple[NumericReference, ...]

    def for_parameter(self, claim_parameter: str) -> tuple[NumericReference, ...]:
        return tuple(e for e in self.entries if e.claim_parameter == claim_parameter)


@dataclass(frozen=True)
class ClaimValue:
    """The claimed number as extracted: canonical unit, and the condition tags the text itself states."""
    parameter: str
    unit: str
    value_min: Decimal
    value_max: Decimal
    conditions: frozenset[str] = frozenset()
    region: str | None = None


@dataclass(frozen=True)
class ReferenceFinding:
    """One comparison. A mismatch always carries the source evidence and the reason it was comparable."""
    outcome: Outcome
    reference_id: str
    rationale: str
    conversion: str
    normalized_min: Decimal | None
    normalized_max: Decimal | None
    reference_point: Decimal | None
    reference_min: Decimal | None
    reference_max: Decimal | None
    reference_unit: str | None
    unit_as_printed: str
    source_url: str
    artifact_sha256: str
    locator: dict[str, str | int]

    @property
    def is_mismatch(self) -> bool:
        return self.outcome in MISMATCHES


# ------------------------------------------------------------------ loading

def _obj(raw: dict, key: str, where: str) -> dict:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise RegistryError(f"{where}: {key} is required")
    return value


def _text(obj: dict, key: str, where: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RegistryError(f"{where}: {key} is required")
    return value


def _decimal(obj: dict, key: str, where: str) -> Decimal:
    value = obj.get(key)
    if not isinstance(value, str) or not _DECIMAL.match(value):
        raise RegistryError(f"{where}: {key} must be a decimal string exactly as printed (not a JSON number)")
    try:
        return Decimal(value)
    except InvalidOperation as exc:  # pragma: no cover - the pattern already excludes it
        raise RegistryError(f"{where}: {key} is not a decimal") from exc


def _iso_date(value: object, key: str, where: str) -> str:
    if not isinstance(value, str):
        raise RegistryError(f"{where}: {key} must be an ISO date")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise RegistryError(f"{where}: {key} must be an ISO date") from exc
    return value


def _texts(value: object, key: str, where: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or (not value and not allow_empty) \
            or any(not isinstance(v, str) or not v.strip() for v in value):
        raise RegistryError(f"{where}: {key} must be a list of non-empty strings")
    return tuple(value)


def _source(raw: dict, where: str) -> NumericSource:
    src = _obj(raw, "source", where)
    url = src.get("url")
    if not isinstance(url, str) or not _HTTPS.match(url):
        raise RegistryError(f"{where}: source.url must be the publisher's https:// URL")
    sha = src.get("artifact_sha256")
    if not isinstance(sha, str) or not _SHA256.match(sha):
        raise RegistryError(f"{where}: source.artifact_sha256 must be 64 lowercase hex")
    size = src.get("artifact_bytes")
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise RegistryError(f"{where}: source.artifact_bytes must be a positive integer")
    effective, note = src.get("effective_date"), src.get("effective_date_note")
    if effective is None:
        if not isinstance(note, str) or not note.strip():
            raise RegistryError(f"{where}: source.effective_date is null, so source.effective_date_note must say why")
    else:
        effective = _iso_date(effective, "source.effective_date", where)
    locator = _obj(src, "locator", f"{where}: source")
    page = locator.get("pdf_page")
    if isinstance(page, bool) or not isinstance(page, int) or page <= 0:
        raise RegistryError(f"{where}: source.locator.pdf_page must be a positive integer")
    anchors = [k for k in ("table", "equation") if isinstance(locator.get(k), str) and locator[k].strip()]
    if not anchors:
        raise RegistryError(f"{where}: source.locator needs the exact table or equation")
    for key, value in locator.items():
        if key != "pdf_page" and (not isinstance(value, str) or not value.strip()):
            raise RegistryError(f"{where}: source.locator.{key} must be a non-empty string")
    return NumericSource(_text(src, "title", where), _text(src, "publisher", where), _text(src, "edition", where),
                         effective, note if effective is None else None, url, sha, size, dict(locator))


def _numeric_entry(raw: dict, allow_synthetic: bool) -> NumericReference:
    if not isinstance(raw, dict):
        raise RegistryError("an entry must be an object")
    ref_id = raw.get("reference_id")
    if not isinstance(ref_id, str) or not _REF_ID.match(ref_id):
        raise RegistryError(f"reference_id {ref_id!r} must match {_REF_ID.pattern}")
    where = ref_id
    if raw.get("kind") != "numeric":
        raise RegistryError(f"{where}: kind must be 'numeric' in a {NUMERIC_REGISTRY_SCHEMA} registry")
    synthetic = raw.get("synthetic", False)
    if not isinstance(synthetic, bool):
        raise RegistryError(f"{where}: synthetic must be true or false")
    if synthetic and not allow_synthetic:
        raise RegistryError(f"{where}: synthetic test fixtures are refused in a production registry")
    parameter = _text(raw, "parameter", where)

    # -- value, exactly as printed
    value = _obj(raw, "value", where)
    point = _decimal(value, "point", f"{where}: value")
    low = high = basis = None
    if value.get("min") is not None or value.get("max") is not None:
        low, high = _decimal(value, "min", f"{where}: value"), _decimal(value, "max", f"{where}: value")
        if not low <= point <= high:
            raise RegistryError(f"{where}: need value.min <= value.point <= value.max")
        basis = _text(value, "range_basis", f"{where}: value")
    elif value.get("range_basis") is not None:
        raise RegistryError(f"{where}: value.range_basis without a printed range")
    unit_as_printed = _text(raw, "unit_as_printed", where)

    # -- unit, dimension and what the number is
    semantics = _obj(raw, "quantity_semantics", where)
    kind = semantics.get("kind")
    if kind not in SEMANTIC_KINDS:
        raise RegistryError(f"{where}: quantity_semantics.kind must be one of {sorted(SEMANTIC_KINDS)}")
    relative_to = semantics.get("relative_to")
    numerator, denominator = (_text(semantics, k, f"{where}: quantity_semantics") for k in ("numerator", "denominator"))
    unit = raw.get("unit")
    if kind in UNITLESS_KINDS:
        if unit is not None:
            raise RegistryError(f"{where}: a {kind} is dimensionless: unit must be null, never a borrowed unit")
        if not isinstance(relative_to, str) or not relative_to.strip():
            raise RegistryError(f"{where}: a {kind} must say what it is relative to")
        dimension = None
    else:
        if unit not in REFERENCE_UNITS:
            raise RegistryError(f"{where}: unit must be one of {sorted(REFERENCE_UNITS)}")
        if relative_to is not None:
            raise RegistryError(f"{where}: relative_to is for scaling and conversion factors only")
        dimension = REFERENCE_UNITS[unit]

    conditions = _texts(raw.get("conditions"), "conditions", where)
    scope = _obj(raw, "scope", where)
    region, tier = scope.get("region"), scope.get("tier")
    for key, item in (("region", region), ("tier", tier)):
        if item is not None and (not isinstance(item, str) or not item.strip()):
            raise RegistryError(f"{where}: scope.{key} must be a non-empty string or null")
    source = _source(raw, where)

    # -- rights
    rights = _obj(raw, "rights", where)
    if rights.get("status") not in RIGHTS_STATUSES:
        raise RegistryError(f"{where}: rights.status must be one of {sorted(RIGHTS_STATUSES)}")
    if rights["status"] != "cleared":
        raise RegistryError(f"{where}: rights are not cleared; the value cannot be stored or redistributed")
    rights_fields = tuple(_text(rights, k, f"{where}: rights") for k in ("basis", "reference", "restrictions"))

    # -- how a claim is compared with it
    comparison = _obj(raw, "comparison", where)
    conversion = comparison.get("conversion")
    claim_parameter, claim_unit = comparison.get("claim_parameter"), comparison.get("claim_unit")
    required = comparison.get("required_claim_conditions", [])
    if not isinstance(required, list) or any(not isinstance(t, str) or not _TAG.match(t) for t in required):
        raise RegistryError(f"{where}: comparison.required_claim_conditions must be a list of condition tags")
    tolerance = _obj(comparison, "tolerance", f"{where}: comparison")
    mode = tolerance.get("mode")
    if mode not in TOLERANCE_MODES or set(tolerance) != {"mode"}:
        raise RegistryError(f"{where}: comparison.tolerance is {{'mode': 'printed_range' | 'exact'}} and nothing else: "
                            "a tolerance the source does not print cannot be entered")
    if mode == "printed_range" and low is None:
        raise RegistryError(f"{where}: tolerance printed_range needs a printed range")
    if conversion == NO_CONVERSION:
        if claim_parameter is not None or claim_unit is not None or required:
            raise RegistryError(f"{where}: conversion 'none' takes no claim parameter, unit or conditions")
    else:
        rule = CONVERSION_RULES.get(conversion) if isinstance(conversion, str) else None
        if rule is None:
            raise RegistryError(f"{where}: comparison.conversion must be 'none' or one of {sorted(CONVERSION_RULES)}")
        if kind in UNITLESS_KINDS:
            raise RegistryError(f"{where}: a {kind} has no conversion from a claim; use 'none'")
        if claim_parameter not in PARAMETERS:
            raise RegistryError(f"{where}: comparison.claim_parameter must be one of {sorted(PARAMETERS)}")
        if claim_unit not in UNITS or UNITS[claim_unit] != PARAMETERS[claim_parameter][0]:
            raise RegistryError(f"{where}: comparison.claim_unit does not fit {claim_parameter}")
        if rule.name == "identity":
            if claim_unit != unit:
                raise RegistryError(f"{where}: identity needs the claim unit to be the reference unit ({unit})")
        elif (claim_unit, unit) != (rule.claim_unit, rule.reference_unit):
            raise RegistryError(f"{where}: rule {rule.name} converts {rule.claim_unit} to {rule.reference_unit} only")
        if not rule.preconditions <= set(required):
            raise RegistryError(f"{where}: rule {rule.name} requires the claim conditions {sorted(rule.preconditions)}")
        if not required:
            # `conditions` (the source's words) is never empty; a comparable entry must turn at least
            # one of them into a tag the claim has to state, or its applicability would go unchecked.
            raise RegistryError(f"{where}: a comparable entry needs at least one required_claim_conditions tag; "
                                "an entry whose applicability cannot be checked uses conversion 'none'")
    invariant = comparison.get("invariant_condition_axes", [])
    if not isinstance(invariant, list) or any(not isinstance(a, str) or not _AXIS.match(a) for a in invariant):
        raise RegistryError(f"{where}: comparison.invariant_condition_axes must be a list of condition axes")
    invariance_basis = comparison.get("invariance_basis")
    if invariant:
        if conversion == NO_CONVERSION:
            raise RegistryError(f"{where}: conversion 'none' takes no invariant_condition_axes")
        if set(invariant) & {condition_axis(t) for t in required}:
            raise RegistryError(f"{where}: an axis the entry requires a value on cannot also be invariant")
        if not isinstance(invariance_basis, str) or not invariance_basis.strip():
            raise RegistryError(f"{where}: invariant_condition_axes need invariance_basis: where the source says the "
                                "value holds whatever the claim states on those axes")
    elif invariance_basis is not None:
        raise RegistryError(f"{where}: invariance_basis without invariant_condition_axes")

    # -- verification
    verification = _obj(raw, "verification", where)
    machine = _obj(verification, "machine_read", f"{where}: verification")
    machine_read = f"{_text(machine, 'tool', where)} on {_iso_date(machine.get('date'), 'machine_read.date', where)}"
    human = _obj(verification, "human", f"{where}: verification")
    status = human.get("status")
    if status not in HUMAN_STATUSES:
        raise RegistryError(f"{where}: verification.human.status must be one of {sorted(HUMAN_STATUSES)}")
    verified_by, verified_at = human.get("verified_by"), human.get("verified_at")
    evidence_ref, evidence_sha = human.get("evidence_ref"), human.get("evidence_sha256")
    if status == "verified":
        if not isinstance(verified_by, str) or not verified_by.strip():
            raise RegistryError(f"{where}: verified needs verification.human.verified_by (a named person)")
        verified_at = _iso_date(verified_at, "verification.human.verified_at", where)
        if not isinstance(evidence_ref, str) or not _EVIDENCE_REF.match(evidence_ref):
            raise RegistryError(f"{where}: verified needs evidence_ref, a file under {EVIDENCE_DIR}")
        if not isinstance(evidence_sha, str) or not _SHA256.match(evidence_sha):
            raise RegistryError(f"{where}: verified needs evidence_sha256 of that evidence file")
        if evidence_sha == source.artifact_sha256:
            raise RegistryError(f"{where}: the evidence file is a separate record, not the artifact itself")
    elif any(v is not None for v in (verified_by, verified_at, evidence_ref, evidence_sha)):
        raise RegistryError(f"{where}: a pending entry names no verifier, date or evidence")

    return NumericReference(
        reference_id=ref_id, parameter=parameter, point=point, range_min=low, range_max=high, range_basis=basis,
        unit_as_printed=unit_as_printed, unit=unit, dimension=dimension, semantic_kind=kind, relative_to=relative_to,
        numerator=numerator, denominator=denominator, conditions=conditions, region=region, tier=tier, source=source,
        rights_basis=rights_fields[0], rights_reference=rights_fields[1], rights_restrictions=rights_fields[2],
        claim_parameter=claim_parameter, claim_unit=claim_unit, conversion=conversion,
        required_claim_conditions=frozenset(required), invariant_condition_axes=frozenset(invariant),
        invariance_basis=invariance_basis, tolerance_mode=mode, machine_read=machine_read,
        human_status=status, verified_by=verified_by, verified_at=verified_at, evidence_ref=evidence_ref,
        evidence_sha256=evidence_sha,
        limitations=_texts(raw.get("limitations", []), "limitations", where, allow_empty=True), synthetic=synthetic)


def load_numeric_registry(data: dict, *, allow_synthetic: bool = False) -> NumericRegistry:
    """Validate an already-parsed schema-2 document (the caller reads the file). May be empty."""
    if not isinstance(data, dict) or data.get("schema") != NUMERIC_REGISTRY_SCHEMA:
        raise RegistryError(f"schema must be {NUMERIC_REGISTRY_SCHEMA!r}")
    version = data.get("registry_version")
    if not isinstance(version, str) or not _TOKEN.match(version):
        raise RegistryError("registry_version must be a short printable token")
    raw_entries = data.get("entries")
    if not isinstance(raw_entries, list):
        raise RegistryError("entries must be a list")
    entries = tuple(_numeric_entry(raw, allow_synthetic) for raw in raw_entries)
    ids = [e.reference_id for e in entries]
    if len(set(ids)) != len(ids):
        raise RegistryError("reference_id values must be unique")
    return NumericRegistry(version, registry_digest(data), entries)


# ------------------------------------------------------------------ comparison

def compare(claim: ClaimValue, entry: NumericReference) -> ReferenceFinding:
    """Compare one claimed value with one reference entry. Deterministic, exact decimal arithmetic."""
    if not all(isinstance(v, Decimal) and v.is_finite() for v in (claim.value_min, claim.value_max)):
        raise ValueError("claim values must be finite Decimals")
    if claim.value_min > claim.value_max:
        raise ValueError("claim value_min must not exceed value_max")

    def finding(outcome: Outcome, rationale: str, low: Decimal | None = None,
                high: Decimal | None = None) -> ReferenceFinding:
        return ReferenceFinding(
            outcome=outcome, reference_id=entry.reference_id, rationale=rationale, conversion=entry.conversion,
            normalized_min=low, normalized_max=high, reference_point=entry.point, reference_min=entry.range_min,
            reference_max=entry.range_max, reference_unit=entry.unit, unit_as_printed=entry.unit_as_printed,
            source_url=entry.source.url, artifact_sha256=entry.source.artifact_sha256,
            locator=dict(entry.source.locator))

    if not entry.usable:
        return finding("reference_unverified",
                       "No human has verified this entry against the hashed artifact; it is never used to judge a claim.")
    if entry.conversion == NO_CONVERSION:
        return finding("not_comparable", f"A {entry.semantic_kind} stored for reference: no rule converts a claim to it.")
    rule = CONVERSION_RULES[entry.conversion]
    if claim.parameter != entry.claim_parameter or claim.unit != entry.claim_unit:
        return finding("not_comparable",
                       f"Rule {rule.name} compares {entry.claim_parameter} in {entry.claim_unit} only; the claim is "
                       f"{claim.parameter} in {claim.unit}. Different quantities are never converted.")
    missing = sorted(entry.required_claim_conditions - claim.conditions)
    if missing:
        return finding("out_of_scope", f"The claim does not state the conditions this entry applies to: {missing}.")
    uncovered = sorted(t for t in claim.conditions - entry.required_claim_conditions
                       if condition_axis(t) not in entry.invariant_condition_axes)
    if uncovered:
        # The claim is about a narrower or different situation than the entry describes, and nobody
        # recorded that the source value holds across it. Not a mismatch: UNRESOLVED, for a human.
        return finding("out_of_scope", f"The claim states conditions this entry does not cover: {uncovered}. "
                                       "Unresolved: a human must decide whether the reference applies.")
    if entry.region is not None and claim.region != entry.region:
        return finding("out_of_scope", f"The entry applies to region {entry.region!r}; the claim states "
                                       f"{claim.region!r}.")
    low, high = claim.value_min * rule.factor, claim.value_max * rule.factor
    how = f"{rule.name}: {rule.rationale}"
    if entry.tolerance_mode == "printed_range":
        inside = entry.range_min <= low and high <= entry.range_max
        return finding("within_printed_range" if inside else "outside_printed_range",
                       f"{how} Compared with the range the source prints ({entry.range_basis}).", low, high)
    equal = low == high == entry.point
    return finding("equal_to_printed_value" if equal else "differs_from_printed_value",
                   f"{how} Compared with the printed value; the source prints no range.", low, high)
