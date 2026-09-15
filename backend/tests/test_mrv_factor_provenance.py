"""MRV provenance with factors as the database stores them.

`emission_factors.verification_status` is an upper-case enum (VERIFIED,
PENDING_VERIFICATION, ...). A fully verified factor set must produce no
`factor_unverified` warning and no `factor_provenance_unavailable` warning; a
pending factor must still be flagged.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mrv import manifest as m  # noqa: E402
from tests.test_mrv_export import FACTOR_SET, FACTOR_SET_ROW, SEASON, SUCCEEDED_CARBON, FakeCarbon, FakeRead, generate  # noqa: E402


def _factor_sets(statuses: list[str]):
    rows = copy.deepcopy(FACTOR_SET_ROW)
    for factor, status in zip(rows[FACTOR_SET]["factors"], statuses):
        factor["verification_status"] = status
    return rows


def _codes(manifest):
    return [w["code"] for w in manifest["warnings"]]


def test_database_verified_status_raises_no_provenance_warnings():
    carbon = {**SUCCEEDED_CARBON, "scenario": "actual"}
    result, _, _, _ = generate(read=FakeRead(factor_sets=_factor_sets(["VERIFIED", "VERIFIED"])), carbon=FakeCarbon(carbon))
    manifest = result["manifest"]
    assert m.WarningCode.FACTOR_UNVERIFIED not in _codes(manifest)
    assert m.WarningCode.FACTOR_PROVENANCE_UNAVAILABLE not in _codes(manifest)
    provenance = manifest["provenance"]["emission_factor_sets"][0]
    assert provenance["factor_set_id"] == FACTOR_SET and len(provenance["factors"]) == 2
    assert manifest["carbon"]["per_crop_season"][SEASON]["status"] == "succeeded"


def test_pending_factor_is_still_reported_as_unverified():
    result, _, _, _ = generate(read=FakeRead(factor_sets=_factor_sets(["VERIFIED", "PENDING_VERIFICATION"])),
                               carbon=FakeCarbon(SUCCEEDED_CARBON))
    warning = next(w for w in result["manifest"]["warnings"] if w["code"] == m.WarningCode.FACTOR_UNVERIFIED)
    assert warning["related"]["factor_codes"] == ["n2o_direct"]


def test_other_warnings_remain_when_provenance_is_complete():
    result, _, _, _ = generate(read=FakeRead(factor_sets=_factor_sets(["VERIFIED", "VERIFIED"])), carbon=FakeCarbon(SUCCEEDED_CARBON))
    codes = _codes(result["manifest"])
    assert m.WarningCode.EVIDENCE_CHECKSUM_MISSING in codes or m.WarningCode.STEP_INCOMPLETE in codes
