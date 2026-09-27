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
by any workflow on a pushed branch of this repo, so the rule is enforced by
review: `ci.yml` must never reference `secrets.*` (it references none), and
only `staging-e2e.yml` may. After upgrading, move the three into a `staging`
environment with a required reviewer and add `environment: staging` to the
secret-bearing jobs. Recommended later: a `production` environment (required
reviewers, `main` only, no automatic trigger). There is no production CD here.

### Bootstrap (one-time, before the first merge)

`workflow_dispatch` only works once the workflow file is on the default
branch. The first validation therefore used a **temporary** `push` trigger for
exactly `ci/agricarbon-production-grade` (the branch of PR #1), plus a
matching `push` leg in every job's `if:`. Both are removed before merge; the
merged file only has `workflow_dispatch`.

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
