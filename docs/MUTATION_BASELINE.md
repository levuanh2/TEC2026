# Mutation testing baseline

Strict CI (`.github/workflows/strict-ci.yml`, job *Mutation testing*) runs
mutmut 2.5.1 on three critical modules and **gates them with a ratchet**
(`scripts/ci/mutation_ratchet.py`, baseline `scripts/ci/policy/mutation.json`,
self-test `scripts/ci/mutation_ratchet_selftest.py` in PR CI). A module fails
when it loses a killed mutant, gains a survivor that is not in its accepted
list, or changed since triage (the policy pins the module's sha256: mutmut
numbers mutants by position, so an edit means re-triaging). Every accepted
survivor carries a class (B, C, D; E only with a recorded decision) and a
reason. A real test gap (A) is never accepted.

Core V1 hardening, measured locally on commit a9a685b with the strict-ci test
sets (2026-10-03):

| Module | Before | After | A | B | C | D | E |
|---|---|---|---|---|---|---|---|
| `carbon/engine.py` | 66/133 | **81/133** | 0 | 10 | 0 | 42 | 0 |
| `recommendation/rules.py` | 45/97 | **71/97** | 0 | 7 | 0 | 19 | 0 |
| `infrastructure/memberships.py` | 10/13 | **12/13** | 0 | 1 | 0 | 0 | 0 |

"Before" is GitHub run 36330193098 (commit a71c47a, 2026-09-27). Closing the A
items added `tests/test_carbon_engine_contract.py`,
`tests/test_recommendation_contract.py` and two `test_memberships.py` cases;
the strict-ci matrix now runs them. No Carbon factor, formula or expected value
changed: the tests pin identity, contracts and boundaries only. Engine mutants
116, 118 and 120 (class D before) died with the provenance-warning tests.

## Categories

**Equivalent / likely equivalent** -- no observable behaviour changes.
- engine 4-7, 9-13: `CarbonResult` field defaults replaced; `calculate_carbon`
  always passes every field. 90: `origin.split(":", 1)` -> `split(":", 2)` on
  `straw:<method>`, which has one colon.
- rules 1, 24, 34: logger name / log message text. 3, 4: defaults of the
  `CarbonCalculator` Protocol stub (never executed). 6-8, 10: dataclass
  defaults always overwritten. 9: `str | None` -> `str & None` in a lazily
  evaluated annotation.
- memberships 1: `value.replace("Z", "+00:00")` -- Python 3.11
  `datetime.fromisoformat` parses `Z` itself.

**Missing meaningful test (A)** -- all killed by the Core V1 hardening; kept
for the record of what each test pins:
- engine 1: `ENGINE_VERSION` is persisted with every result and drives
  idempotency; pin it in a golden test. 45: the `compute_input_hash` payload
  separator (a changed hash silently defeats idempotent save); golden hash.
  14, 16: `CarbonResult.to_dict()` keys `crop_season_id`,
  `water_regime_applied` (API contract). 27: `calculate_carbon` default
  scenario `as_recorded`. 76, 77: cultivation-days boundary (0 and 1 days).
  82: yield boundary in (0, 1] kg for CO2e/kg. 114, 115, 117, 119: the
  "parameter without a source citation" provenance warning is never exercised
  (relevant to the factor-provenance rule: a factor with an empty source must
  surface).
- rules 22, 31: the AWD rule computes baseline/proposal with `persist=False`;
  `persist=True` would silently write Carbon results as a side effect of
  generating a recommendation -- assert no persistence. 11-14, 56-59: rule
  codes / versions are the persisted identity (idempotent regeneration); pin
  them. 18, 20, 29, 61: title / compared-to / reason / disclaimer become
  `None` unnoticed; assert non-empty user-facing strings. 39: recommendation
  `type`. 41, 42, 51-55, 97: evidence keys (provenance of a recommendation).
  46: `delta <= 0` boundary (a 0 < delta <= 1 kg saving). 91, 93: data-task
  `input_hash`.
- memberships 12, 13: `active_memberships()` with the default clock
  (`now=None`) is never called by a test.

**Low-value text** -- human-readable Vietnamese messages, warnings and list
separators (engine 42-44, 49-50, 55-57, 61-62, 66-68, 70, 73-75, 78, 80, 83-84,
95-98, 101-102, 104-105, 107-112, 121, 124, 126, 128, 131-133;
rules 17, 19, 26-28, 35, 60, 63-65, 67-68, 70-71, 73-74). Asserting exact prose
would make tests brittle; the codes and structure around them are what clients
read. Accepted in the ratchet as class D, one entry per mutant.
