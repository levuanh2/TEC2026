"""Trusted-reference registry: a small, versioned, auditable list of canonical values and
qualitative constraints that extracted claims are compared with.

Format (JSON, schema "kn-reference-registry-1"):
{"schema": "kn-reference-registry-1", "registry_version": "<token>", "entries": [
   {"reference_id": "ref-...", "parameter": "<claims.PARAMETERS or claims.ASSERTIONS key>",
    "kind": "quantity" | "qualitative",
    "source": {"title", "locator", "document_version", "url" (https or null), "artifact_sha256" (or null)},
    "scope": "<applicability in words>", "stage": null | "<claims.STAGES name>",
    "value_min", "value_max", "unit", "tolerance"            (quantity only; unit in claims.UNITS)
    "assertion_holds": true | false                           (qualitative only)
    "rationale": "...",
    "verification": {"status", "pointer", "evidence_ref", "verified_by", "note"}}]}

Verification status says HOW MUCH the entry itself is trusted. It is never inferred:
  independently_verified  the value was checked against the publisher's artifact. Needs the
                          artifact sha256, a stored evidence file sha256 and a named verifier.
  engine_config_pointer   points at an existing Carbon/MRV configuration value. Only as good as
                          that configuration, and NOT independently verified here.
  project_policy          an AgriCarbon product rule, not an external agricultural authority.
  unverified              recorded for review, not yet checked.
  synthetic_test_fixture  test data. Refused unless allow_synthetic=True, so it can never enter
                          the production registry.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Literal

from knowledge.ids import sha256_hex
from knowledge.integrity.claims import ASSERTIONS, PARAMETERS, STAGES, UNITS

REGISTRY_SCHEMA = "kn-reference-registry-1"
VERIFICATION_STATUSES = frozenset({"independently_verified", "engine_config_pointer", "project_policy", "unverified",
                                   "synthetic_test_fixture"})

_REF_ID = re.compile(r"^ref-[a-z0-9][a-z0-9-]{1,62}$")
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_STAGE_NAMES = frozenset(name for name, _ in STAGES)


class RegistryError(ValueError):
    """The registry document is malformed or claims more trust than it records evidence for."""


@dataclass(frozen=True)
class ReferenceSource:
    title: str
    locator: str
    document_version: str
    url: str | None
    artifact_sha256: str | None


@dataclass(frozen=True)
class ReferenceEntry:
    reference_id: str
    parameter: str
    kind: Literal["quantity", "qualitative"]
    source: ReferenceSource
    scope: str
    rationale: str
    verification_status: str
    verification_pointer: str | None = None
    evidence_ref: str | None = None
    verified_by: str | None = None
    stage: str | None = None
    value_min: float | None = None
    value_max: float | None = None
    unit: str | None = None
    tolerance: float = 0.0
    assertion_holds: bool | None = None

    @property
    def independently_verified(self) -> bool:
        return self.verification_status == "independently_verified"


@dataclass(frozen=True)
class ReferenceRegistry:
    registry_version: str
    digest: str                              # sha256 of the canonical JSON: the audit identity
    entries: tuple[ReferenceEntry, ...]

    def for_parameter(self, parameter: str) -> tuple[ReferenceEntry, ...]:
        return tuple(e for e in self.entries if e.parameter == parameter)


def registry_digest(data: dict) -> str:
    return sha256_hex(json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")))


def _text(obj: dict, key: str, where: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RegistryError(f"{where}: {key} is required")
    return value


def _number(obj: dict, key: str, where: str) -> float:
    value = obj.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise RegistryError(f"{where}: {key} must be a finite number")
    return float(value)


def _entry(raw: dict, allow_synthetic: bool) -> ReferenceEntry:
    if not isinstance(raw, dict):
        raise RegistryError("an entry must be an object")
    ref_id = raw.get("reference_id")
    if not isinstance(ref_id, str) or not _REF_ID.match(ref_id):
        raise RegistryError(f"reference_id {ref_id!r} must match {_REF_ID.pattern}")
    where = ref_id
    parameter, kind = raw.get("parameter"), raw.get("kind")
    src = raw.get("source")
    if not isinstance(src, dict):
        raise RegistryError(f"{where}: source is required")
    url, artifact = src.get("url"), src.get("artifact_sha256")
    if url is not None and (not isinstance(url, str) or not re.match(r"^https://\S+$", url)):
        raise RegistryError(f"{where}: source.url must be https:// or null")
    if artifact is not None and (not isinstance(artifact, str) or not _SHA256.match(artifact)):
        raise RegistryError(f"{where}: source.artifact_sha256 must be 64 lowercase hex or null")
    source = ReferenceSource(_text(src, "title", where), _text(src, "locator", where),
                             _text(src, "document_version", where), url, artifact)

    ver = raw.get("verification")
    if not isinstance(ver, dict):
        raise RegistryError(f"{where}: verification is required")
    status = ver.get("status")
    if status not in VERIFICATION_STATUSES:
        raise RegistryError(f"{where}: verification.status must be one of {sorted(VERIFICATION_STATUSES)}")
    if status == "synthetic_test_fixture" and not allow_synthetic:
        raise RegistryError(f"{where}: synthetic test fixtures are refused in a production registry")
    pointer, evidence, verifier = ver.get("pointer"), ver.get("evidence_ref"), ver.get("verified_by")
    if status == "independently_verified":
        if artifact is None or url is None or not isinstance(evidence, str) or not _SHA256.match(evidence) \
                or not isinstance(verifier, str) or not verifier.strip():
            raise RegistryError(f"{where}: independently_verified needs source.url, source.artifact_sha256, "
                                "verification.evidence_ref (sha256) and verification.verified_by")
        if evidence == artifact:
            raise RegistryError(f"{where}: evidence_ref must be a separate evidence file, not the artifact itself")
    if status in ("engine_config_pointer", "project_policy") and (not isinstance(pointer, str) or not pointer.strip()):
        raise RegistryError(f"{where}: {status} needs verification.pointer")

    stage = raw.get("stage")
    if stage is not None and stage not in _STAGE_NAMES:
        raise RegistryError(f"{where}: stage must be one of {sorted(_STAGE_NAMES)} or null")
    common = dict(reference_id=ref_id, parameter=parameter, kind=kind, source=source,
                  scope=_text(raw, "scope", where), rationale=_text(raw, "rationale", where),
                  verification_status=status, verification_pointer=pointer, evidence_ref=evidence,
                  verified_by=verifier, stage=stage)

    if kind == "quantity":
        if parameter not in PARAMETERS:
            raise RegistryError(f"{where}: quantity parameter must be one of {sorted(PARAMETERS)}")
        unit = raw.get("unit")
        if unit not in UNITS:
            raise RegistryError(f"{where}: unit must be one of {sorted(UNITS)}")
        if UNITS[unit] != PARAMETERS[parameter][0]:
            raise RegistryError(f"{where}: unit {unit} ({UNITS[unit]}) does not fit {parameter} "
                                f"({PARAMETERS[parameter][0]}); incompatible units are never compared")
        low, high = _number(raw, "value_min", where), _number(raw, "value_max", where)
        tolerance = _number(raw, "tolerance", where) if raw.get("tolerance") is not None else 0.0
        if low > high or tolerance < 0:
            raise RegistryError(f"{where}: need value_min <= value_max and tolerance >= 0")
        if tolerance > max(abs(low), abs(high)):
            raise RegistryError(f"{where}: tolerance larger than the value itself would silence every conflict")
        if raw.get("assertion_holds") is not None:
            raise RegistryError(f"{where}: a quantity entry has no assertion_holds")
        return ReferenceEntry(**common, value_min=low, value_max=high, unit=unit, tolerance=tolerance)
    if kind == "qualitative":
        if parameter not in ASSERTIONS:
            raise RegistryError(f"{where}: qualitative parameter must be one of {sorted(ASSERTIONS)}")
        holds = raw.get("assertion_holds")
        if not isinstance(holds, bool):
            raise RegistryError(f"{where}: assertion_holds must be true or false")
        if any(raw.get(k) is not None for k in ("value_min", "value_max", "unit", "tolerance")):
            raise RegistryError(f"{where}: a qualitative entry has no value, unit or tolerance")
        return ReferenceEntry(**common, assertion_holds=holds)
    raise RegistryError(f"{where}: kind must be 'quantity' or 'qualitative'")


def load_registry(data: dict, *, allow_synthetic: bool = False) -> ReferenceRegistry:
    """Validate an already-parsed registry document (the caller reads the file)."""
    if not isinstance(data, dict) or data.get("schema") != REGISTRY_SCHEMA:
        raise RegistryError(f"schema must be {REGISTRY_SCHEMA!r}")
    version = data.get("registry_version")
    if not isinstance(version, str) or not _TOKEN.match(version):
        raise RegistryError("registry_version must be a short printable token")
    raw_entries = data.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise RegistryError("entries must be a non-empty list")
    entries = tuple(_entry(raw, allow_synthetic) for raw in raw_entries)
    ids = [e.reference_id for e in entries]
    if len(set(ids)) != len(ids):
        raise RegistryError("reference_id values must be unique")
    return ReferenceRegistry(version, registry_digest(data), entries)
