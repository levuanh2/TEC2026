# CI pipeline

Two GitHub Actions workflows:

| Workflow | Trigger | Secrets | Touches hosted? | Required for merge |
|---|---|---|---|---|
| `.github/workflows/ci.yml` | PR → `main`, push to `main`, manual | **none** | **never** | yes: the single `ci-gate` job |
| `.github/workflows/staging-e2e.yml` | manual only, `main` only | staging | yes: Render + hosted Supabase | no |

`ci.yml` runs against mock data or an isolated Supabase stack started inside the
runner. It never deploys, never publishes an APK, and never applies a migration
anywhere except that throw-away stack.

## 1. `ci.yml` DAG

```
 stage 1 (parallel, no needs)                stage 2                         gate
 ─────────────────────────────                ───────                         ────
 backend-unit ─────────────┬──────────────▶ backend-db-integration ──┐
 migration-static ─────────┴──────────────▶ rls-security ─────────────┤
 web-unit ────────────────────────────────▶ playwright-mock ──────────┤
 flutter-unit ────────────────────────────▶ flutter-android ──────────┤
 backend-startup ─────────────────────────────────────────────────────┤
 web-build ───────────────────────────────────────────────────────────┼──▶ ci-gate
 secret-scan ─────────────────────────────────────────────────────────┤
 workflow-lint ───────────────────────────────────────────────────────┤
 dependency-audit ────────────────────────────────────────────────────┘
```

Each stage-2 job waits only on the cheap jobs that would make it pointless
(no Playwright if `tsc`/Vitest fail, no Gradle build if `flutter analyze`
fails, no Supabase stack if unit tests or migration naming fail). Everything
else starts at once. The repository is private, and on the free plan Actions
minutes are metered, so failing cheap first also saves minutes.

| Job | What it proves | Timeout |
|---|---|---|
| `backend-unit` | `compileall`, full pytest **without** any Supabase settings (DB/config-gated tests skip) | 15 min |
| `backend-startup` | fresh venv from `backend/requirements.txt` only → `import main` → Render start command → `/health`, `/docs`, `/openapi.json` = 200; torch/torchvision absent (CV answers 503 by design) | 10 min |
| `migration-static` | names `YYYYMMDDHHMMSS_snake.sql`, unique versions, UTF-8, non-empty; on a PR, no edited/deleted base migration and no new version ≤ the base's newest | 5 min |
| `backend-db-integration` | local Supabase: **every migration applied from an empty DB, fail-fast**, applied set == files, PostgREST boots, schema validator, CI seed, then the **whole** backend suite with DB + configured app; at most 2 skips (the CV real-model smoke, which needs an uncommitted `ml/runs/` checkpoint); coverage | 25 min |
| `rls-security` | local Supabase + seed, then the PostgREST/Auth probes: lifecycle + membership (Flutter sync calls, 36 cases), P0 security (50), P1 correctness (30), write reliability (19), public sign-up disabled (5) | 25 min |
| `web-unit` | `npm ci`, `tsc -b`, Vitest (2 workers) + coverage, 0 skips allowed | 15 min |
| `web-build` | `npm run build` with `VITE_USE_MOCK_DATA=false` and placeholder endpoints; fails if a mock fixture id (`farm-demo-01`, `crop-demo-01`) is in `dist/` or the API URL was not compiled in | 10 min |
| `playwright-mock` | Farmer + Management mock suite (`playwright.config.ts`, CI mode: 2 workers, no retries, `forbidOnly`), 0 skips allowed | 25 min |
| `flutter-unit` | Flutter 3.47.4: `pub get --enforce-lockfile`, `flutter analyze` (fails on any issue), `flutter test` (`test/` only) + coverage | 20 min |
| `flutter-android` | `flutter build apk --debug --target-platform android-arm64` (Java 17, Gradle heap bounded to 4 GB) | 30 min |
| `secret-scan` | gitleaks 8.30.1 over the working tree and full history; no tracked keystore / `key.properties` / `.env` / SQLite / DB file | 10 min |
| `workflow-lint` | actionlint (+ shellcheck on every `run:` block) | 5 min |
| `dependency-audit` | pip-audit, `npm audit --audit-level=high`, osv-scanner on `pubspec.lock` | 10 min |
| `ci-gate` | fails unless **every** job above has result `success` (failed, cancelled or skipped all fail it) | 5 min |

Concurrency: a newer push to the same PR cancels the older run. Runs on `main`
are never cancelled, so every commit that lands gets a complete result.
Permissions: `contents: read` only, and every checkout uses
`persist-credentials: false`. Every action is pinned to a full commit SHA, with
its version in a comment. Downloaded tools (gitleaks, actionlint, osv-scanner)
are pinned and SHA-256-verified.

### Test-discovery floors

`ci_report.py --min-total` fails a job whose suite suddenly reports far fewer
tests (a broken glob or import). Floors are about 10% under the counts when CI
was introduced. They are not targets. Raise them as suites grow, and lower one
only with the reason in the PR.

| Suite | Count at introduction | Floor (`env` in ci.yml) |
|---|---|---|
| Backend pytest | 840 | 750 |
| Vitest | 472 | 425 |
| Playwright mock | 90 | 80 |
| Flutter | 401 | 360 |

### Why the DB jobs seed the CI database

Several real-database tests (`test_activity_rls_policies`, `test_p0/p1_*`,
`test_write_response_atomicity`, `test_straw_quickfix_persistence`) read the
demo tenant instead of creating rows, and the Carbon persist gate needs a
published factor set. `scripts/ci/seed_ci_db.py` provisions the empty CI
database the way the hosted one was provisioned. It uses only the project's own
tools and documented steps:
`import_factor_set.py --apply --publish` (+ `--verify`), `seed_demo_data.py`,
`create_farmer_qa_identity.py`, the three private Storage buckets that the
baseline migration says to create through the Storage API, one user with no
membership, and one CV model version labelled as a CI fixture. Passwords are
random per run and never printed. The script refuses any `SUPABASE_URL` that
is not `127.0.0.1`/`localhost`.

### Path filtering: deliberately not used (yet)

Every job runs on every PR. Backend changes can break Flutter (shared
PostgREST/RLS contract) and web (API shapes); migration changes affect all
three. Skipping by path would risk exactly the cross-layer breakage this
pipeline exists to catch. Revisit only with measured run times, and keep
`ci-gate` requiring every job (a path-skipped job would need an explicit
"not applicable" success, not a skip).

## 2. What runs where

| | PR → main | push to main | manual (`ci.yml`) | `staging-e2e.yml` |
|---|---|---|---|---|
| All `ci.yml` jobs | ✓ | ✓ | ✓ | |
| `web-dist-ci-placeholder-endpoints` artifact | | ✓ | ✓ | |
| `android-debug-apk-NOT-FOR-DISTRIBUTION` artifact | | ✓ | ✓ | |
| Render health + cold start | | | | ✓ |
| Render API flow on a disposable tenant | | | | ✓ |
| Disposable-tenant PostgREST probes on hosted Supabase | | | | ✓ (input `db_probes`, default on) |
| Read-only real-data browser specs | | | | opt-in (input `browser_readonly`, default off) |

### Real / hosted Playwright specs never run in `ci.yml`

`playwright.config.ts` excludes them **by file name** (`testIgnore`), not just
by their own env guards:

* `*-real*.spec.ts`: 13 files, 35 tests; they belong to `playwright.real.config.ts`.
* `redesign-qa.spec.ts`: 15 tests, a hosted credentialed pass that is only
  selected when `REDESIGN_QA=true` (developers run it through the default
  config).

The CI job also sets `REAL_E2E=false` / `REDESIGN_QA=false` and allows **0
skipped** tests, so a new gated spec that slips into the mock selection fails
loudly instead of being silently skipped.

## 3. Staging E2E (`staging-e2e.yml`)

Manual (`workflow_dispatch`) from `main`. Every job that reads a secret
re-checks, in its own `if:`, that the repository is `levuanh2/TEC2026` and that
the event and ref are trusted. There is no `pull_request` or
`pull_request_target` trigger, so fork PRs and arbitrary branches can never
reach it or its secrets. The concurrency group never cancels, because an
interrupted script could skip its cleanup. No shared QA identity is needed.

| Job | Mutates? | What |
|---|---|---|
| `preflight` | no | trusted repo/ref; the 3 secrets present; URL is a hosted `https://*.supabase.co` |
| `render` | no | wakes the API (Render Free cold start tolerated up to 180 s, reported separately from warm latency), `/docs`, web `/` and an SPA deep link |
| `render-flow` | **disposable tenant only** | `backend/scripts/staging_render_flow.py` through the **deployed Render API**: manager `/v1/me` → provision a farmer with farm + plot → farmer sign-in with the temporary password → `/v1/farmer/scope` → create season (+ default batch) → irrigation activity create / idempotent replay / edit / list → Carbon readiness → manager MRV case list → mark harvested → new write refused `422 invalid_crop_season_state` → anonymous read 401 |
| `db-probes` | **disposable tenant only** | hosted PostgREST lifecycle probe (36 cases, the Flutter sync calls) + public sign-up disabled; catches a hosted project that drifted from `supabase/migrations` |
| `browser-readonly` | no | **opt-in** (`browser_readonly`, default off, never on push): `web-real-data` + `farmer-real-data` on the Render web app; needs the optional QA identity secrets |

**Hosted jobs run one after another.** `render-flow` and `db-probes` both compare global
table row counts before and after, so `db-probes` waits for `render-flow` (and still runs if it
failed). On the first GitHub run they overlapped and each reported the other's in-flight tenant as
a row-count difference, although every functional check passed and a direct lookup on hosted found
0 leftover rows and 0 leftover Auth users for both run tags. Real users writing to the staging
project during a run can still cause such a difference; the run then fails and a direct lookup by
run tag decides.

**Cleanup guarantee.** Each script tags everything with a unique run id,
deletes it in `finally` (rows, the farmer that the API provisioned, the
manager, profiles), then fails the run if any counted table's row count
differs from before **or** any Auth user with the run's e-mail prefix still
exists. On failure it prints the run tag and the created ids (never tokens or
passwords). This was verified by making Auth user deletion raise: the run
exited 1 with `cleanup_no_auth_users_left` failing and the ids listed.

`hosted_p0_security_smoke.py` and `hosted_p1_correctness_smoke.py` are **not**
in the staging workflow: they open raw `psycopg` connections, which would put
the hosted Postgres URL into CI. They run in `ci.yml` (`rls-security`) against
the identical migrated schema.

Cold start measured on 2026-09-27: `/health` answered 200 after **33.8 s**.

### Secrets (repository secrets, minimum set)

| Name | Used by | Why |
|---|---|---|
| `STAGING_SUPABASE_URL` | preflight, render-flow, db-probes | hosted project |
| `STAGING_SUPABASE_PUBLISHABLE_KEY` | render-flow, db-probes | sign in the disposable users |
| `STAGING_SUPABASE_SERVICE_ROLE_KEY` | render-flow, db-probes | create and delete the disposable tenant and users |
| `STAGING_MANAGER_EMAIL`/`_PASSWORD`, `STAGING_FARMER_EMAIL`/`_PASSWORD` | browser-readonly only | optional; **not set** |
| `STAGING_API_URL`, `STAGING_WEB_URL` | variables, optional | default to the `*.onrender.com` staging URLs |

No `SUPABASE_DB_URL` secret exists: nothing in CI needs the hosted Postgres
connection string. The hosted project is the staging/demo project that Render
staging uses; no production credential is stored.

**Plan limitation.** The repository is private on the GitHub Free plan.
Environment secrets, required reviewers and branch protection for private
repos need GitHub Pro/Team (the branch-protection API answers 403). The
secrets are therefore **repository** secrets. Repository secrets are readable
by any workflow that **anyone with write access** pushes on any branch of this
repo (today: the owner and one other collaborator with `write`). No workflow
condition can prevent that; only environment secrets with required reviewers
can. Until then the rule is enforced by review: `ci.yml` must never reference
`secrets.*` (it references none), and only `staging-e2e.yml` may. After upgrading, move the three into a `staging`
environment with a required reviewer and add `environment: staging` to the
secret-bearing jobs. Recommended later: a `production` environment (required
reviewers, `main` only, no automatic trigger). There is no production CD here.

### Bootstrap (one-time, before the first merge)

`workflow_dispatch` only works once the workflow file is on the default
branch. The first validation therefore used a **temporary** `push` trigger for
exactly `ci/agricarbon-production-grade` (the branch of PR #1), plus a
matching `push` leg in every secret-bearing job's `if:` that also requires the
pusher and triggering actor to be the repository owner. That run passed on
GitHub Actions on 2026-09-27 (commit `df0be1b`, run 36306809693: Render flow
17/17, hosted lifecycle probe 36/36 with cleanup verified, sign-up disabled 5/5),
and the trigger and its `if:` legs were then removed. The merged file only has
`workflow_dispatch`.

**Cleanup hardening (from the read-only review).** In `staging_render_flow.py`
and `hosted_lifecycle_rls_probe.py`, every cleanup call, the discovery
`select`s included, is retried and recorded instead of raised, so one failed
lookup cannot skip the remaining deletes. The probe now also fails
(`--enforce`) when a cleanup step failed or an Auth user of the run survived.
Before this, a failed Auth user deletion left row counts "restored" (the
profile row was still deleted) and passed silently. Verified by fault
injection: transient failure → retried, clean, exit 0; permanent failure →
exit 1 with the tag and ids; surviving users → exit 1. `hosted_p0_security_smoke.py`
keeps its older cleanup: it only runs in `ci.yml` against the runner's
throw-away stack (it needs a direct Postgres URL, which CI never has for
hosted), so an interrupted cleanup there cannot orphan hosted data.

## 4. Secrets and configuration

| Class | Where | Examples |
|---|---|---|
| Public test config | in the workflow file | `VITE_USE_MOCK_DATA=false`, placeholder `https://api.ci.invalid`, local Supabase demo keys printed by `supabase status` |
| Secret CI config | none | `ci.yml` needs no secrets at all |
| Hosted E2E config | 3 repository secrets (above) | hosted URL, publishable key, service role |

No developer `.env` is read in CI: runners have none, and `load_settings()`
only reads `backend/.env` when it exists. No `.env.ci.example` is needed. Never
commit `.jks`, `key.properties`, signing passwords or base64 keys; the
`secret-scan` job fails on any tracked keystore/`key.properties`/`.env`.

### Python interpreters (never the developer's global Python)

* `scripts/ci/backend_startup_smoke.sh` is the only helper that creates a venv.
  It calls `<venv>/bin/python` (or `Scripts/python.exe`) directly, never
  `activate`, and aborts **before any install** unless `sys.prefix` is exactly
  that venv. Verified: global Python → refused, another venv → refused, the
  right venv → allowed.
* `ci_report.py`, `check_migrations.py` and the JSON parse in
  `supabase_stack.sh` are standard-library only and install nothing.
  `seed_ci_db.py` re-uses its own interpreter (`sys.executable`).
* In the workflows, `pip install` targets the runner's `actions/setup-python`
  interpreter on a throw-away VM.

**Known local contamination (2026-09-27, developer machine only).** Before the
guard existed, the first local startup-smoke run sourced a Windows venv's
`activate` under Git Bash, which left PATH on the global Python 3.11, so pip
installed there: **pip 24.0 → 26.2.1, pydantic → 2.13.5, pydantic_core →
2.46.5**. The previous pydantic version was not recorded, so no rollback was
guessed. `pip check` afterwards reports 19 conflicts; exactly one comes from
this upgrade, **`openrouter 1.0.18` requires `pydantic<2.13`**, and the other 18
involve packages this work never touched. Status:
**LOCAL_GLOBAL_PYTHON_NEEDS_MANUAL_REPAIR** (the owner decides the pydantic
version). This does not affect repository CI, which never uses that
interpreter.

## 5. Migration policy

* CI **validates** migrations: static rules on every PR, plus a clean apply of
  every file in order on an empty database (`supabase start` stops at the
  first failing file, and `supabase_stack.sh` then requires the applied
  versions to equal the files on disk).
* CI **never applies** migrations to a hosted project. Neither workflow runs
  `supabase db push`, `supabase link` or any migration against a hosted URL.
* Hosted migration remains a manual, approved operation: one migration/batch,
  verify, then the next (`docs/MIGRATION_HISTORY.md`, "Hosted migration
  runbook").
* Never edit a migration that is already on `main`; add a new one.
  `migration-static` enforces this on PRs.

## 6. Build artifacts

| Artifact | When | Retention | Note |
|---|---|---|---|
| `reports-*` (JUnit, coverage XML/lcov/json) | every run | 14 days | small |
| `playwright-failure-traces` | on failure | 7 days | mock data only, no credentials |
| `backend-startup-log`, `supabase-logs-*` | on failure | 7 days | local demo keys only |
| `web-dist-ci-placeholder-endpoints` | main / manual | 7 days | build check, **not deployable** (`VITE_*` are build-time) |
| `android-debug-apk-NOT-FOR-DISTRIBUTION` | main / manual | 7 days | debug-signed, arm64, no `--dart-define`s |

Never uploaded: `.env`, credentials, database dumps, local SQLite, keystores.

**Release APK.** CI builds debug only. On `main`, `app/android/app/build.gradle.kts`
still has the Flutter template's release config, which signs with the
**debug** key. A `--release` build from CI would therefore look like a release
but be debug-signed. The fail-closed release signing
(`release/agricarbon-flutter-staging-signing`, not merged) refuses that. A
future release workflow should build `--release` with the keystore from an
approved environment and run `dart run tool/verify_release_apk.dart` on the
output.

## 7. Security checks

* **Secret scanning**: gitleaks over the tree and full history with
  `.gitleaks.toml`. The default rules stay on. The allowlist only covers value
  **shapes** that the entropy rule mistook for secrets here (snake_case field
  keys, UUID idempotency keys, the temporary-password alphabet, one test
  fixture), never whole files. Verified: planted Stripe and service-role-JWT
  strings are still reported. GitHub's own secret scanning / push protection
  is unavailable for this private repo on the Free plan. History still
  contains a pre-rotation **demo** password (documented in `AGENTS.md`, not
  rewritten); it does not match the default rules.
* **Dependency security** (all clean when introduced: 0 npm, 0 PyPI, 0 pub
  advisories):
  * npm: `npm audit --audit-level=high`: high/critical fail, low/moderate are
    reported only.
  * PyPI: `pip-audit` on the resolved `backend/requirements.txt`. It has no
    reliable severity, so any advisory fails. To accept one, add
    `--ignore-vuln <ID>` in `ci.yml` with the reason and a revisit date in the
    PR.
  * pub: `osv-scanner` on `app/pubspec.lock`. Any advisory fails; accept one
    via `app/osv-scanner.toml` `[[IgnoredVulns]]` with a reason.
  * `ml/requirements.txt` (training stack) is not audited: it is not deployed.

## 8. Coverage (reported, not enforced)

| Layer | Line coverage at introduction | Measured by |
|---|---|---|
| Backend (app code, excl. tests and scripts; full suite with DB) | 89.6% | `backend-db-integration`, `backend/.coveragerc` |
| Web (`src/**`, excl. tests and mocks) | 63.8% (statements 60.6%, branches 51.1%, functions 53.3%) | `web-unit`, `vite.config.ts` |
| Flutter (`lib/`) | 66.1% | `flutter-unit` (`flutter test --coverage`) |

**Policy for now: report-only. No threshold is enforced** (not even the
no-regression gate below). Every run prints each layer's line coverage in its
job summary and uploads the XML/lcov/json files.

Proposed for a later PR: **no-regression** rather than a fixed number. Once
`main` has a persisted baseline to compare against (e.g. the coverage
artifact of the latest green `main` run), fail a PR when its layer's line
coverage drops more than 0.5 points below `main`'s. A fixed threshold would be
arbitrary, and 80% would block the web layer for reasons unrelated to the
change.

## 9. Resource control

| Runner | Setting |
|---|---|
| pytest | single process (no xdist) |
| Vitest | `--maxWorkers=2` |
| Playwright | `workers: 2` in CI, `retries: 0` |
| Flutter test | `--concurrency=2` |
| Gradle | `org.gradle.jvmargs=-Xmx4g` via `~/.gradle/gradle.properties` (the project file asks for 8 GB) |

Flaky policy: no retries for unit/integration tests. Playwright retries are 0
because no project policy allows them. A test that needs a retry is a bug to
root-cause, and the trace from the failing attempt is uploaded.

## 10. Branch protection (recommended, not applied)

When the plan allows it (GitHub Pro/Team, or a public repo), set on `main`:
require a pull request; require status check **`ci-gate`** (only that one,
since it already depends on every job); optionally require branches to be up
to date; block force pushes and deletion; require conversation resolution.
Do not list individual jobs as required checks: the gate is the stable name.

## 11. Local equivalents

Run from the repository root unless noted. Backend commands run **from
`backend/`** (a repo-root run fails 18 tests on a relative config path).

| Job | Command |
|---|---|
| backend-unit | `cd backend && SUPABASE_URL= SUPABASE_DB_URL= SUPABASE_SERVICE_ROLE_KEY= SUPABASE_PUBLISHABLE_KEY= python -m pytest tests -q` (the empty values override `backend/.env`) |
| backend-startup | `bash scripts/ci/backend_startup_smoke.sh` (Git Bash works: it calls the venv's interpreter directly) |
| migration-static | `python scripts/ci/check_migrations.py --base-ref origin/main` |
| backend-db-integration | Docker + Supabase CLI: `SUPABASE_PROJECT_ID=tec2026-ci bash scripts/ci/supabase_stack.sh` (prints `export` lines; `eval` them), then `python scripts/ci/seed_ci_db.py`, then `cd backend && python -m pytest tests -q --cov --cov-config=.coveragerc` |
| rls-security | same stack + seed, then `cd backend && python scripts/hosted_lifecycle_rls_probe.py --enforce`, `python scripts/hosted_p0_security_smoke.py`, `…p1_correctness_smoke.py`, `…write_reliability_smoke.py`, `verify_public_signup_disabled.py` |
| web-unit | `cd web-dashboard && npm ci && npx tsc -b && npx vitest run --coverage` |
| web-build | `cd web-dashboard && VITE_USE_MOCK_DATA=false VITE_API_BASE_URL=https://api.ci.invalid npm run build` |
| playwright-mock | `cd web-dashboard && CI=1 npx playwright test` (stop anything already on :5173 first) |
| flutter-unit | `cd app && flutter pub get --enforce-lockfile && flutter analyze && flutter test --coverage` |
| flutter-android | `cd app && flutter build apk --debug --target-platform android-arm64` |
| secret-scan | `gitleaks dir . --config .gitleaks.toml --redact` and `gitleaks git . --config .gitleaks.toml --redact` (a local tree also holds your gitignored `.env` files, so scan `git archive HEAD` output if you want CI's view) |
| workflow-lint | `actionlint` |
| dependency-audit | `pip-audit -r backend/requirements.txt`, `cd web-dashboard && npm audit --audit-level=high`, `osv-scanner scan source --lockfile app/pubspec.lock` |

**Ordinary tests never reach hosted (`backend/tests/conftest.py`, `tests/_db_target.py`).**
`backend/.env` holds the HOSTED project and `load_settings()` fills every *absent* variable from
it (PowerShell `$env:X = ''` deletes X rather than emptying it). Before any test module is
imported, the guard classifies `SUPABASE_DB_URL` (by the host libpq would really reach,
including `?host=`, multi-host lists, `PGHOST`/`PGSERVICE`), `SUPABASE_URL` and
`SUPABASE_JWKS_URL`. Local = `localhost`, a loopback IP or a Unix socket.
- A non-local value from `backend/.env` is ignored for the session: every `SUPABASE_*` value
  from the file becomes `""`, i.e. the CI no-DB state. The DB tests skip and the session
  header says so.
- A non-local value set explicitly in the environment aborts the session (exit code 4) before
  any connection is opened.
- A deliberate hosted test run needs **both** `ALLOW_HOSTED_DB_TESTS=i-understand-this-touches-hosted`
  and `AGRICARBON_HOSTED_TEST_PROJECT_REF=<ref>` in the environment (never from `.env`). Every
  target must then be exactly that project's API host, pooler (`postgres.<ref>` on
  `*.pooler.supabase.com`) or direct (`db.<ref>.supabase.co`) endpoint.

Defence in depth: `tests/__init__.py` runs the same guard for any `tests.*` import (so `--noconftest`,
`--confcutdir` and an import outside pytest are covered) and installs connection-boundary checks:
`psycopg.Connection.connect` re-validates the effective target (libpq `host` and `hostaddr` resolve
independently, e.g. `PGHOSTADDR`), and Python sockets refuse any non-loopback TCP destination.

Hosted operations are a separate path and never go through pytest:
`backend/scripts/hosted_*.py`, `import_factor_set.py`, `ingest_knowledge.py --target <ref>` and
the migration runbook (`docs/MIGRATION_HISTORY.md`).

**Local Supabase notes.** Use `SUPABASE_PROJECT_ID=tec2026-ci` so the CI stack
gets its own Docker volumes. Plain `supabase start` reuses an existing
`TEC2026` volume ("Starting database from backup…") that may predate the latest
migrations. `supabase_stack.sh` catches that by comparing applied versions to
the files. Tear it down with
`SUPABASE_PROJECT_ID=tec2026-ci supabase stop --no-backup`. The script needs
`psql`, which the Ubuntu runners have.

## 12. Failure investigation

1. Open the run and read the `ci-gate` summary: one row per job.
2. Each test job's summary has a table (total/passed/failed/skipped/coverage)
   and `::error` annotations with the reason (failed tests, discovery below
   the floor, unexpected skips).
3. Artifacts: `reports-*` (JUnit), `playwright-failure-traces`
   (`npx playwright show-trace <zip>`), `supabase-logs-*` (one log per
   container), `backend-startup-log`.
4. Reproduce with the local equivalent above.
5. "Job was not started because recent account payments have failed…" is
   GitHub billing, not the code: nothing ran.

## 13. Known gaps

* No backend linter/formatter/type checker, and no web ESLint/Prettier, is
  configured; CI runs what exists (`compileall`, `tsc -b`, `flutter analyze`).
  `dart format` is not enforced (16 files differ today).
* `ml/tests` (CV training utilities) is not in CI.
* See "Legacy scripts" for `hosted_e2e_rest.py`.
* Flutter `integration_test/` needs an emulator and the hosted project; it is
  not run in CI.
* No iOS build.

## 14. Legacy scripts

`backend/scripts/hosted_e2e_rest.py` is **LEGACY / NOT PART OF CURRENT CI**
(its header says so; it is kept, not deleted). It last matched the schema on
2026-09-08: its seeded PDF export row violates `mrv_export_snapshot_lineage_chk`
(20260913150000, pdf/xlsx must reference their JSON snapshot), and the MRV
export read path has changed since. Its MRV coverage is replaced by:

| Replacement | Where | Covers |
|---|---|---|
| `test_mrv_export.py` (59), `test_mrv_pdf.py` (39), `test_mrv_xlsx.py` (42), `test_mrv_canonical_carbon.py` (6), `test_mrv_factor_provenance.py` (3) | `ci.yml` backend jobs (DB job against real Postgres) | snapshot manifest and lineage, PDF/XLSX rendering, canonical Carbon, factor provenance |
| `hosted_p0_security_smoke.py` `m7_*` (12 checks) | `ci.yml` `rls-security` | manager creates an XLSX export, rows written, FastAPI download + SHA, snapshot download, metadata, object stored, bucket private, anonymous/public-URL read denied, client upload/delete denied |
| `staging_render_flow.py` `manager_mrv_cases_read_200` | `staging-e2e.yml` | MRV case read on the deployed Render API |

Its non-MRV reads (hierarchy, tenant isolation 404s) are covered by
`test_read_repository.py`, the P0 smoke and the lifecycle probe.

## 15. Hardening v2: strict quality gates

Every gate fails closed with a stable error code. Policy data lives in
`scripts/ci/policy/` (`policy.json`, `migrations.sha256`, `schema-audit.json`).
Relaxing it (lower floor/baseline/minimum, larger tolerance or allowlist) fails
`workflow-policy` unless a PR commit carries `CI-Policy-Change: <reason>`.
Coverage baselines are always read from the **base branch**, so a PR cannot
lower its own bar.

| Gate | Job | Codes |
|---|---|---|
| actionlint + shellcheck, SHA pins, timeouts, permissions, bypass patterns (`\|\| true`, `set +e`, `continue-on-error`, `except: pass`), ci-gate completeness, missing scripts, syntax, `pull_request_target` | workflow-policy | `CI_*` |
| skip/xfail/fixme/todo and `@ts-ignore`/Dart ignore inventories (increase fails), `.only`, analyzer relaxation, auth sign-up config, gitleaks allowlist shape | workflow-policy | `DISABLED_TEST_ADDED`, `FOCUSED_TEST`, `TS_SUPPRESSION_ADDED`, `DART_IGNORE_ADDED`, `ANALYZER_RELAXED`, `AUTH_SIGNUP_POLICY`, `GITLEAKS_BROAD_ALLOWLIST` |
| discovery floors, exact skip budget, security probe minimums, per-module minimums for security-critical test files (`protected_tests`: deleting them and padding elsewhere fails) | every test job | `TEST_DISCOVERY_REGRESSION`, `UNEXPECTED_SKIP`, `PROBE_REGRESSION`, `PROTECTED_TEST_REGRESSION` |
| coverage: global (-0.5 pp), 16 critical backend modules, changed lines >= 80% | backend-db-integration, web-unit, flutter-unit | `COVERAGE_REGRESSION`, `CRITICAL_COVERAGE_REGRESSION`, `CHANGED_CODE_COVERAGE` |
| migration checksum manifest | migration-static | `MIGRATION_MODIFIED/DELETED/UNREGISTERED`, `MANIFEST_REWRITTEN` |
| migration upgrade: seeded base -> head (N-1 -> N when none added); every base table keeps its row count and base-column checksum unless `docs/MIGRATION_DATA_CHANGES.md` ACKs it; catalog == fresh; lifecycle 36/36 | migration-upgrade | `MIGRATION_DATA_CHANGED` |
| schema invariants, RLS on all tables, no anon/`true` policies, no privilege broadening, SECURITY DEFINER search_path/dynamic SQL, catalog snapshot | backend-db-integration (`db_audit.py`) | `SCHEMA_INVARIANT`, `RLS_*`, `PRIVILEGE_BROADENED`, `SECURITY_DEFINER`, `SCHEMA_AUDIT_DRIFT` |
| OpenAPI == generated; breaking changes need `ACK` in `docs/API_BREAKING_CHANGES.md` | openapi-contract | `OPENAPI_DRIFT`, `OPENAPI_BREAKING` |
| error envelope on every route, 401 semantics, validation 422, finite numbers, boundaries, malformed input, log safety | backend tests (`test_api_contract_hardening.py`) | - |
| fresh-venv isolation, all production modules import, undeclared deps, resolved drift (warn) | backend-startup (`python_deps_check.py`) | `ENV_NOT_ISOLATED`, `IMPORT_BOUNDARY`, `UNDECLARED_DEPENDENCY` |
| web dist: mock ids, dev API, server secrets (value shapes), test artifacts, bundle growth > 20% | web-build | `DIST_*`, `BUNDLE_GROWTH` |
| console/page errors, failed requests, HTTP errors in every mock test; axe serious/critical = 0 and no overflow at 390/768/1024/1440 on 6 key screens | playwright-mock | - |
| release debug-signing guard, cleartext, debuggable, exported components, permissions, APK identity/mode, APK secrets | flutter-android (`android_check.py`) | `RELEASE_DEBUG_SIGNING`, `APK_*`, `MANIFEST_*` |
| advisories with id/reason/owner/expiry exceptions, dependency diff summary | dependency-audit | `DEP_*` |
| artifacts carry commit + SHA-256 + build mode | web-build, flutter-android | - |

`strict-ci.yml` (nightly + manual): backend suite in random order (seed =
run number, printed), critical DB suites twice in fresh processes, property
tests (`backend/tests_strict`), mutation testing (ratchet, fails on a lost
kill or an untriaged survivor; `docs/MUTATION_BASELINE.md`), installed dependencies == `backend/constraints.txt` (fails),
license inventory (report).

**Backend dependency lock.** `backend/requirements.txt` states what the backend
needs (human-maintained `>=` ranges) and applies `backend/constraints.txt` with
`-c constraints.txt`. The constraints file pins the whole resolved set (direct
and transitive) of a clean Linux venv on Python 3.11.9 to exact versions, so
every `pip install -r requirements.txt` -- Render's `buildCommand`, each CI job,
a developer venv -- installs exactly what CI tested, and an upstream release
cannot change staging or production. Both PR CI (`backend-startup`) and
strict-ci compare a fresh install's `pip freeze` with it and fail on any
difference (`DEP_DRIFT`: a package the lock does not pin, or a pin pip did not
honour). `ci_policy.py` `DEP_SOURCE` allows exactly one option line in
`backend/requirements.txt`, `-c constraints.txt`, and only `name==version` lines
in the constraints file; both files are guarded paths (CODEOWNERS). The test
tools in `requirements.txt` (pytest, httpx, pypdf) are part of the set: Render
installs the same single file.

The test jobs that also need the CV stack (`backend-unit`,
`backend-db-integration`, strict `backend-order-and-repeatability`) install
torch/torchvision and `ml/requirements.txt` under the same lock
(`-c backend/constraints.txt`): if one of them needs another version of a locked
package, pip fails instead of moving it. The next step proves it
(`dep_audit.py --drift <freeze> --lock-subset`, `DEP_LOCK_CHANGED`): extra
test-only packages are allowed, but every locked package must be at its locked
version, so the backend tests run on the set Render installs.
`ci_policy.py` `CI_UNCONSTRAINED_INSTALL` refuses a job that installs next to
the backend without the lock or without that proof;
`scripts/ci/dep_lock_selftest.py` (workflow-policy) tests both gates on
synthetic input.

Updating a dependency is a PR of its own: change the pin in
`backend/constraints.txt` (and the range in `requirements.txt` if needed), let
CI run, take the new freeze from that run's `backend-startup` artifact (never a
developer machine; Windows resolves extra packages such as `colorama`), review
the diff, merge. The flip side of the lock: a security fix upstream no longer
arrives on its own. A new advisory against a pinned version fails
`dependency-audit` on every PR until a PR bumps that pin (or a time-boxed
`dependency_exceptions` entry, with owner and expiry, accepts it), so plan
regular dependency-update PRs. Refresh `docs/openapi.json` with it when FastAPI moves: a
FastAPI upgrade alone changes the generated spec (0.141 renders uploads as
`contentMediaType` and adds `input`/`ctx` to `ValidationError`) and nests
included routers so a flat `app.routes` walk sees no `/v1` routes -- the route
sweep therefore enumerates `app.openapi()["paths"]`.

### CI exceptions

| ID | Rule | Reason | Scope | Owner | Added | Review/expiry |
|---|---|---|---|---|---|---|
| EXC-SKIP-CV | skip budget | real-model CV smoke needs an uncommitted `ml/runs/` checkpoint | 2 exact test ids, backend-db | backend | 2026-09-27 | when a CI model artifact exists |
| EXC-DB-01 | PRIVILEGE_BROADENED | legacy default grant: anon has write grants on `season_recommendations`; RLS on, no anon policy | 1 table | backend | 2026-09-27 | 2026-12-31 (revoke via migration) |
| EXC-DB-02 | function EXECUTE | `soft_delete_activity` (SECURITY DEFINER) executable by anon/authenticated; checks `user_can_delete_activity` first, raises 42501 (verified as anon) | 1 RPC | backend | 2026-09-27 | 2026-12-31 |
| EXC-API-01 | 401 sweep | `GET /v1/carbon/scenarios` is public: static scenario names, no tenant data | 1 route | backend | 2026-09-27 | 2026-12-31 |
| EXC-API-02 | 401 sweep | the 3 Carbon routes answer 401 `missing_authorization` (Flutter `carbon_api_service` maps it); every other route `unauthenticated`. All answer 401 before 422/503 | 3 routes | backend | 2026-09-27 | 2026-12-31 |
| EXC-DB-03 | RLS_PERMISSIVE | `mrv_step_catalog_select` is `USING (true)` for authenticated: static MRV step catalog, no tenant data | 1 policy | backend | 2026-09-27 | 2026-12-31 |
| EXC-WEB-01 | page-health | `api/carbon.ts`, `api/engine.ts`, `api/organizations.ts` are not mock-gated; in mock mode they hit a port Chrome refuses (127.0.0.1:9) | 6 exact requests + 1 console text | web | 2026-09-27 | 2026-12-31 (mock-gate the modules) |
| EXC-ANDROID-01 | RELEASE_DEBUG_SIGNING | `main` still signs release with the debug key; fail-closed signing is on the unmerged release branch | `app/android/app/build.gradle.kts` | app | 2026-09-27 | **2026-10-31, enforced in code** |

DB exceptions (EXC-DB-01..03) are data in `policy.json` `db_exceptions`, read by
`db_audit.py`; growing them is a policy relaxation.

### CI change review

These are high-impact: `.github/workflows/`, `scripts/ci/` (gates and
`policy/`), `supabase/migrations/`, and every file in `policy.json`
`guarded_paths` -- including the configs that decide what is measured
(`backend/.coveragerc`, `web-dashboard/vite.config.ts` coverage excludes, the
page-health `ALLOWED` list in `tests/e2e/fixtures.ts`, `app/analysis_options.yaml`,
`.gitleaks.toml`, pytest config/conftest/markers, `docs/API_BREAKING_CHANGES.md`,
`docs/MIGRATION_DATA_CHANGES.md`).

- `workflow-policy` fails (`CI_GUARDED_CHANGE` / `CI_POLICY_RELAXED`) unless a
  commit in the PR carries `CI-Policy-Change: <reason>`; the changed files and
  relaxations are listed in the job summary.
- The trailer is self-declared. It makes the change explicit; it is not an
  approval. Approval is **CODEOWNERS**: `.github/CODEOWNERS` owns every guarded
  path (`CI_CODEOWNERS_MISSING` keeps it in sync), and GitHub reads it from the
  base branch, so a PR cannot drop itself out of review.
- **Required repository setting** (not something a workflow can enforce): branch
  protection on `main` with "Require a pull request", "Require review from Code
  Owners" and required status check `ci-gate`. Without it, CI is advisory.

Dependency manifests are guarded too (`backend/requirements.txt`,
`ml/requirements.txt`, `web-dashboard/package.json` + `package-lock.json`,
`app/pubspec.yaml` + `pubspec.lock`): they decide which pytest / vitest /
playwright binary runs the gates. `DEP_SOURCE` additionally requires every entry
to come from the public registry (npm: registry.npmjs.org + sha512 integrity;
pub: pub.dev; pip: no URL, path or index option). A dependency bump therefore
carries the trailer and gets CODEOWNERS review, next to the dependency-audit
diff summary.

**Positive auth coverage for every protected route.** A "no token -> 401" sweep
also passes a route that rejects *every* caller. `backend/tests/route_auth_manifest.py`
classifies every operation of the app's OpenAPI (not only `/v1`) as `PUBLIC`
(only `GET /v1/carbon/scenarios` and `GET /health`), `POSITIVE` or `EXCEPTION`
(documented `EXC-AUTH-*` id; none today). The inventory also walks the app's
real routing table, before and inside its lifespan: served operations must
equal the OpenAPI ones, and a mount, a websocket/raw route, any
`include_in_schema=False` (even set at runtime), an `on_event` hook or an
unreviewed middleware fails (`UNINVENTORIED_ROUTE`) -- so nothing the app
serves can sit outside the manifest. `test_route_auth_inventory.py` (no database, both backend jobs)
fails with `PROTECTED_ROUTE_POSITIVE_COVERAGE_MISSING` for an operation missing
from the manifest, rejects stale entries, a non-2xx `POSITIVE` expectation and
any write that is not `POSITIVE`. `test_route_positive_auth.py` (DB job) then
builds a disposable tenant on the local stack -- Auth Admin users, password
grant, real GoTrue JWTs -- and drives all 53 protected operations over HTTP
through `main.app`: the persona gets the SUCCESS status (season + batch,
activities, Carbon result, recommendation, CV inference, MRV export/render/
download, provisioning ...), the same request without a token gets 401, and
where the manifest says `deny`, an active manager of another cooperative gets
403/404 first. A manifest entry whose request never ran fails with
`PROTECTED_ROUTE_POSITIVE_CASE_MISSING`. CV inference runs with an untrained
model of the production architecture (CI has no checkpoint); upload, scope,
Storage and rows are real. The tenant is deleted afterwards. The manifest and
both tests are guarded with protected minimums (54 and 9 passed).

**`backend/main.py` is a CODEOWNERS path (since 2026-09-27).** The rule was:
application wiring stays outside CI policy unless a concrete bypass of every
gate is shown. The adversarial review showed one: a lifespan in `main.py` can
schedule a task that inserts a route *after* startup, which no import- or
lifespan-time inventory sees. So `main.py` (the app, its middleware and its
lifespan) is guarded, and `ROUTE_MUTATION` (workflow-policy) fails when any
backend/ml production module edits the routing table directly
(`.routes.append/insert/...`, `routes[...] =`), calls `add_route` /
`add_api_route` / `mount`, uses `setattr`, or touches `lifespan` /
`lifespan_context`, calls `include_router` (outside the reviewed line in
`main.py`), or calls a route method as a plain function -- routes come only
from `@router.<method>` decorators on MODULE-LEVEL functions (the AST rejects
a route decorator inside a function or class: it would register when called,
e.g. from a timer), and the inventory requires every module that declares
routes to be loaded once `main` is imported (no late `importlib` routes).
Exact exception: the reviewed `FastAPI(..., lifespan=lifespan)` line (the
lifespan only releases pools on shutdown).

**The routing table is frozen at runtime.** Static rules cannot see every
alias (`route = app.get` inside a function a timer calls later), so `main.py`
ends with `freeze_routing(app)` (`backend/infrastructure/route_freeze.py`,
guarded): every router's route list becomes a tuple and every registration
method -- `add_api_route`, `include_router`, `mount`, the `get`/`post`/...
decorators, `on_event` -- raises, as does rebinding `routes`, `router` or
`lifespan_context`. A late registration now fails loudly in production instead
of serving an uninventoried operation. `test_routing_is_frozen_after_import`
asserts the frozen state and tries each path. Undoing the freeze
(`__class__ =`, `object.__setattr__`, `frozen_class`) is a `ROUTE_MUTATION`
outside the freezer file itself.

Residual, by design (like obfuscated environment detection): code written to
defeat the scanners -- attribute names assembled at runtime, `getattr` tricks,
eval -- that mutates routing later. No static or dynamic test can rule out
arbitrary self-modifying code; that is code review.

Every gate script a workflow executes is guarded (the application code under test -- `backend/main.py` and the modules it imports, `web-dashboard/src`, `app/lib` -- is not: it is what production runs, it is reviewed like any product change, and the protected suites exercise it): `CI_UNGUARDED_SCRIPT` fails when a
`run:` step calls a script outside `guarded_paths` (the security probes in
`backend/scripts/` print the very `50/50` lines the gate trusts), and
`CI_UNGUARDED_TEST` requires every `protected_tests` module to be guarded.

Test-aware application code (a "defeat device" that behaves only under the
test runner) is narrowed in two ways: `TEST_ENV_DETECTION` fails when
production code (`backend/` outside tests/scripts, `web-dashboard/src`,
`app/lib`) references pytest / `sys.modules` / `PYTEST_*` / `CI` /
`GITHUB_ACTIONS` / `VITEST` / `navigator.webdriver` / `FLUTTER_TEST` /
`Platform.environment` (exact exceptions: `policy.json` `env_detection_allow`),
and backend-startup re-runs the 401 sweep against the live `uvicorn main:app`
process -- the Render start command, with no pytest loaded. Obfuscated
detection can still evade a static scan; that remains code review.

Residual risk, by design: an assertion weakened inside a test that is neither
protected nor guarded (most feature tests, the mock Playwright specs) keeps
counts and coverage green. That is ordinary code review; strict-ci mutation
testing is the automated signal for it.

Residual risk, by design: PR CI runs the PR's own workflow and helper code, so a
PR that edits a gate can make that gate lie. No in-repo check can prevent that
without `pull_request_target` (excluded: it would run with repository secrets
in reach). The defence is the review rule above. Secret scans match value
shapes; a secret deliberately split or encoded to evade them is out of scope
(the scans target accidental leaks).

Dependency advisory exceptions go in `policy.json` `dependency_exceptions`
(id, package, reason, owner, added, expires); expired ones fail CI. There are
none today.

### High-impact changes (review carefully)

`.github/workflows/`, `scripts/ci/`, `scripts/ci/policy/`, `supabase/migrations/`,
`.gitleaks.toml`, `tests/e2e/fixtures.ts` (page-health allowlist),
`docs/API_BREAKING_CHANGES.md`. A PR touching them changes what "green" means:
reviewers check that no gate got weaker, and relaxations carry the trailer.

### Findings from building these gates (product follow-ups, not fixed here unless noted)

- Fixed: activity quantities accepted `Infinity` (NaN failed range checks); now finite-only.
- Fixed: `index.html` declared no favicon: every page logged a 404.
- `docs/openapi.json` was 11 operations stale; regenerated, 5 historical breaks acknowledged.
- Mock mode leaks carbon/readiness/health/organizations calls to the network (EXC-WEB-01); locally they reached `.env`'s backend.
- Fixed (Core V1): Resource Metrics summed with plain float `sum()`, so record order changed the last digit and the single-season and rollup paths disagreed (property test); now `math.fsum` (F-METRICS-FSUM).
- Production code imports `PIL`, `postgrest`, `starlette`, `supabase_auth` that are only transitive dependencies; declare them.
- `infrastructure/auth_admin.py` coverage 42.9%; mutation score of `carbon/engine.py` ~50% despite 96.8% line coverage (Core V1: 81/133, every remaining survivor equivalent or message text; ratcheted).
- Android `allowBackup` is unset (backups on, incl. the Supabase session in SharedPreferences): needs a product decision.
- Licenses: psycopg family is LGPL-3.0 (review).
