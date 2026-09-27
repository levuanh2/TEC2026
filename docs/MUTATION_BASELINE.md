# Mutation testing baseline

Strict CI (`.github/workflows/strict-ci.yml`, job *Mutation testing*) runs
mutmut 2.5.1 on three critical modules and uploads every surviving mutant's diff
(`mutation-<n>` artifacts). The result is **reported, not gated** (status:
PARTIAL): there is no score threshold yet. A future PR introduces a ratchet once
the `missing test` items below are closed, so the bar is set on triaged data,
not an invented number.

Baseline: GitHub run 36330193098 (commit a71c47a, 2026-09-27); totals confirmed
unchanged by strict run 36332895849 (commit 1c3a0fa). Every survivor below was
read from its diff and classified exactly once.

| Module | Survivors | Equivalent / likely equivalent | Missing meaningful test | Low-value text | Needs investigation |
|---|---|---|---|---|---|
| `carbon/engine.py` | 67 of 133 | 10 | 12 | 45 | 0 |
| `recommendation/rules.py` | 52 of 97 | 10 | 26 | 16 | 0 |
| `infrastructure/memberships.py` | 3 of 13 | 1 | 2 | 0 | 0 |

Mutation scores (killed/total, `mutmut junitxml`, printed in the strict job
summary): engine 66/133, rules 45/97, memberships 10/13.

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

**Missing meaningful test** -- real behaviour no test pins. To close first:
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
95-98, 101-102, 104-105, 107-112, 116, 118, 120-121, 124, 126, 128, 131-133;
rules 17, 19, 26-28, 35, 60, 63-65, 67-68, 70-71, 73-74). Asserting exact prose
would make tests brittle; the codes and structure around them are what clients
read. Not counted against a future ratchet.
