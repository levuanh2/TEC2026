"""Import the Carbon parameter YAML as an immutable emission factor set.

    python backend/scripts/import_factor_set.py                 # dry run (default): validate, no DB access
    python backend/scripts/import_factor_set.py --apply         # insert as draft (one transaction)
    python backend/scripts/import_factor_set.py --apply --publish
    python backend/scripts/import_factor_set.py --verify        # compare an existing set with the YAML

Rules (fail closed):
* the YAML must pass `carbon.factor_register.validate_parameter_set` — any error,
  unit mismatch, unverified or missing core factor, duplicate key or unsupported
  code aborts before a single row is written;
* an existing `version_code` is never modified: `--apply` refuses, `--verify`
  compares it row by row with the YAML;
* set + factors are written in one transaction; `--publish` flips the set to
  `published` in that same transaction only after the factor count matches.

Needs SUPABASE_DB_URL for --apply/--verify (backend/.env). Prints a JSON report.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from carbon.factor_register import (  # noqa: E402
    FactorSetValidationError,
    factor_set_row,
    load_parameter_file,
    validate_parameter_set,
)

DEFAULT_FILE = BACKEND_DIR / "config" / "emission_factors.yaml"


def _connect():
    import psycopg
    from infrastructure.config import load_settings

    return psycopg.connect(load_settings().require_db(), autocommit=False)


def _verify(cur, set_id: str, report) -> list[str]:
    cur.execute(
        """select factor_code, factor_value, activity_unit, result_unit, parameter_kind::text,
                  verification_status::text, source_reference, source_table_reference
           from public.emission_factors where factor_set_id = %s""",
        (set_id,),
    )
    stored = {r[0]: r for r in cur.fetchall()}
    problems = []
    expected = {row.factor_code: row for row in report.rows}
    for code in sorted(set(stored) | set(expected)):
        if code not in stored:
            problems.append(f"{code}: missing in database")
        elif code not in expected:
            problems.append(f"{code}: in database but not in YAML")
        else:
            db, yml = stored[code], expected[code]
            if Decimal(str(db[1])) != Decimal(str(yml.factor_value)).quantize(Decimal(1).scaleb(-12)):
                problems.append(f"{code}: value {db[1]} != YAML {yml.factor_value}")
            if db[5] != yml.verification_status:
                problems.append(f"{code}: status {db[5]} != YAML {yml.verification_status}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", default=str(DEFAULT_FILE))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    if args.publish and not args.apply:
        parser.error("--publish requires --apply")

    try:
        root = load_parameter_file(args.file)
    except FactorSetValidationError as exc:
        print(json.dumps({"errors": [str(exc)], "activation_eligible": False}, ensure_ascii=False, indent=2))
        return 2
    report = validate_parameter_set(root)
    summary = report.summary()
    summary["mode"] = "verify" if args.verify else ("apply+publish" if args.publish else "apply" if args.apply else "dry-run")

    if not args.apply and not args.verify:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if report.activation_eligible else 1

    if not report.activation_eligible:
        summary["result"] = "refused: the parameter set is not eligible; nothing was written"
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 1

    set_row = factor_set_row(root)
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute("select id, status::text from public.emission_factor_sets where version_code = %s", (set_row["version_code"],))
        existing = cur.fetchone()
        if args.verify:
            if existing is None:
                summary["result"] = "not found"
                print(json.dumps(summary, ensure_ascii=False, indent=2))
                return 1
            problems = _verify(cur, str(existing[0]), report)
            summary.update(factor_set_id=str(existing[0]), status=existing[1], verify_problems=problems,
                           result="identical to YAML" if not problems else "DIFFERS from YAML")
            conn.rollback()
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0 if not problems else 1
        if existing is not None:
            summary["result"] = f"refused: version_code already exists ({existing[1]}); factor sets are immutable"
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 1
        try:
            cur.execute(
                """insert into public.emission_factor_sets
                     (version_code, name, description, methodology_name, methodology_version, valid_from,
                      source_name, source_url, status)
                   values (%(version_code)s, %(name)s, %(description)s, %(methodology_name)s, %(methodology_version)s,
                           %(valid_from)s, %(source_name)s, %(source_url)s, 'draft') returning id""",
                set_row,
            )
            set_id = str(cur.fetchone()[0])
            for row in report.rows:
                cur.execute(
                    """insert into public.emission_factors
                         (factor_set_id, factor_code, category, gas, activity_unit, result_unit, factor_value,
                          source_reference, notes, parameter_kind, verification_status, source_table_reference,
                          uncertainty_range, applies_to_water_regime, applies_to_pre_season_regime)
                       values (%(factor_set_id)s, %(factor_code)s, %(category)s, %(gas)s, %(activity_unit)s,
                               %(result_unit)s, %(factor_value)s, %(source_reference)s, %(notes)s, %(parameter_kind)s,
                               %(verification_status)s, %(source_table_reference)s, %(uncertainty_range)s,
                               %(applies_to_water_regime)s, %(applies_to_pre_season_regime)s)""",
                    row.as_db_row(set_id),
                )
            cur.execute("select count(*) from public.emission_factors where factor_set_id = %s", (set_id,))
            stored = cur.fetchone()[0]
            if stored != len(report.rows):
                raise RuntimeError(f"stored {stored} factors, expected {len(report.rows)}")
            status = "draft"
            if args.publish:
                cur.execute(
                    "update public.emission_factor_sets set status = 'published', published_at = %s where id = %s",
                    (datetime.now(timezone.utc), set_id),
                )
                status = "published"
            conn.commit()
        except Exception as exc:  # noqa: BLE001 - report and roll back everything
            conn.rollback()
            summary["result"] = f"failed and rolled back: {exc}"
            print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
            return 1
    summary.update(result="imported", factor_set_id=set_id, status=status, factor_count=len(report.rows))
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
