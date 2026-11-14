# Android QA APKs and physical-device QA — 14/11/2026

Debug QA builds only. Not a release: no release signing, no store artifact, no
backend/web deploy, and no hosted Supabase or AI provider was used.

## Side-by-side QA packages

`app/android/app/build.gradle.kts` accepts `-P agricarbon.qaVariant=` on debug
builds only:

| Variant | applicationId | Launcher label |
|---|---|---|
| (none) | `vn.agricarbon.mobile` (unchanged) | AgriCarbon |
| `uipreview` | `vn.agricarbon.mobile.uipreview` | AgriCarbon Preview |
| `localqa` | `vn.agricarbon.mobile.localqa` | AgriCarbon QA |

A release build with the property fails (GradleException). The manifest label is
now the `${appLabel}` placeholder, which defaults to `AgriCarbon`, so a release build keeps its label.
`scripts/ci/android_check.py --package <id>` checks a QA APK. A non-default id
is accepted only with `--mode debug`, and the QA ids are the only ones allowed.
The reset-password deep-link scheme is shared, so Android may show a chooser when
a QA build is installed next to the real app.

## APK A: UI preview (no login, no network)

```powershell
cd app
flutter build apk --debug -t tool/ui_preview.dart -P agricarbon.qaVariant=uipreview
```

`tool/ui_preview.dart` now covers Login, Home and bottom navigation, Pricing,
the selected-plan review, the Q&A screen, the loading/empty/offline/error states,
the brand page (logo sizes and Be Vietnam Pro 400–800) and shared components.
Every page has a "DỮ LIỆU MINH HỌA" banner. The Q&A preview answers on the
device with a labelled fixture that has no numbers. The preview starts no
Supabase, makes no HTTP call and writes no database or shared preferences.
This was checked on the device: the package has no `databases/` or
`shared_prefs/`.

## APK B: local functional QA

The build reads a gitignored dart-define file. `app/config/local-qa.example.json`
shows its shape:

```powershell
flutter build apk --debug --dart-define-from-file=config/local-qa.json -P agricarbon.qaVariant=localqa
adb reverse tcp:55721 tcp:55721   # local Supabase API (throw-away stack, shifted ports)
adb reverse tcp:8010 tcp:8010     # local FastAPI
```

Only a publishable key is used, and it comes from the local stack's
`supabase status`. No service role, Postgres password or provider key goes
into the APK; `android_check.py` passed, and a raw scan found only SDK source
strings. The debug network config allows cleartext only to loopback.
The local backend ran with `RAG_QA_ENABLED=true`, and every
`GEMINI_*`/`DEEPSEEK_*`/`RAG_LLM_*` variable was cleared.

## Local-only Q&A screen

`lib/screens/season_question_screen.dart` and
`lib/services/season_question_api.dart` call
`POST /v1/crop-seasons/{id}/questions` with READ-tier intents only:
explain, data_gap, evidence and compare. recommend and what_if are not
offered. The entry point is "Hỏi đáp về vụ mùa" on the crop season detail
screen. It appears only when the build sets
`--dart-define=AGRICARBON_LOCAL_QA_QUESTIONS=true` (default OFF) and the
season has a server id.

The screen does not keep history. It cancels the request when the screen
closes (one client per request is closed) and has a 45 s timeout. A
generation counter drops late answers. An answer whose `crop_season_id`
differs from the request is not shown. If the signed-in account changes or
signs out, the answer is cleared and the screen closes. Error codes map to the
same Vietnamese messages as the web panel; only transient errors offer
"Thử lại".

## Fixes found on the phone

Round 1: the add-plot dialog overflowed by 72 px in landscape with the
keyboard open at font scale 1.8. A scrollable dialog removed the overflow but
left a scroll area about one line tall.

Round 2 (same phone, defects confirmed before fixing, each with a regression
test that fails without the fix):

- **Add/edit plot and create-farm forms**: these now use the new design
  component `AdaptiveFormDialog`. It is a normal dialog when the free height
  (after system bars and keyboard) fits the fields at the current text scale.
  Otherwise it switches to a full-screen form: Cancel and Save sit in the
  48 dp app bar, the body scrolls, and the focused field is scrolled to the
  middle of the visible area. One `GlobalKey` keeps the fields' text and focus
  across the switch and across rotation. Once full-screen, the form stays
  full-screen until it closes. Validation and the dialog results did not
  change. The round-1 global dialog-theme inset was reverted.
  Tests: `test/dialog_landscape_keyboard_test.dart`.
- **Every `AppScaffold` form with the keyboard open in a cramped
  layout** (landscape phone, ~100 dp free): in "Ghi: Bón phân" the full header
  left ~43 dp and the focused field stayed under the keyboard. There was no
  overflow error, so it showed up only in screenshots. Now, only while the
  keyboard is open and the free height is below 260 dp: the header becomes
  48 dp (no subtitle, title capped at 1.2x), a pinned bottom bar moves to the
  end of the scroll area, and `FocusReveal` scrolls the focused field into
  view. Other layouts are unchanged. Tests: `test/app_scaffold_cramped_test.dart`.
- **Session loss left the previous account's pages on screen**: after a
  server-side session revocation, AuthGate showed Login, but the pushed farm,
  plot and season pages stayed on top of it. AuthGate now pops every route
  above the root when the phase leaves `authenticated`. Tests:
  `test/auth_gate_session_loss_test.dart`. This bug is on `main` as well;
  this PR did not introduce it.

## Physical device run (Xiaomi 24094RAD4G, Android 16 / SDK 36, arm64-v8a)

PASS: install next to the existing app, cold and warm start, logo and fonts,
login against the local stack, Home, the four tabs, farm, plot and season
pages, carbon result (readiness, no stored result), resource efficiency,
Pricing (both audiences), plan review, system back, scrolling, keyboard
open/close, font scale 1.8, landscape, offline banner and reconnect, Q&A
(explain, data_gap, evidence, backend unreachable then retry), an irrigation
write synced to the local DB, logout, and account isolation (an outsider sees
no farms and cannot reach the season or its answer).

NOT TESTED: running a carbon calculation (the fixture season lacks five
inputs), cancelling Q&A by leaving mid-request (covered only by a widget test),
and screens below 360 dp width on a real device.

## Round 2 physical QA (14/11/2026)

The local stack, local FastAPI and fixture accounts were the same as in round
1, and no AI provider was configured. A local logging proxy between the
phone and FastAPI recorded the method, path, the JWT `sub` (never the token),
status, and whether the client hung up. It delayed `/questions` to open a
cancellation window.

| Check | Result |
|---|---|
| Leave Q&A while the request waits before the backend | PASS 3/3: the client closed the connection, and the request never reached FastAPI |
| Leave Q&A after the backend answered (response held) | UI cancelled and the answer was dropped. The backend was NOT cancelled: FastAPI completed with 200, and Q&A persists nothing |
| Second question while one is pending | PASS: suggestions and Send are disabled, and only 1 request was sent |
| Switch to another season with the same label (`DEMO-HT-2026` on plot 1.2) | PASS: no stale answer, and the new request used the new season id |
| Sign out and sign in as another account during a pending question | PASS: after logout only the new account's `sub` appears; 0 requests carry the previous account's credentials |
| Session revoked on the server while a question is pending (local `jwt_expiry=60`) | Q&A closed itself, and the request was cancelled before the backend. Before the AuthGate fix, stale pages stayed above Login; after it, Login is the root |
| Backend vanishes mid-request, then returns | PASS: offline message plus Thử lại; the retry got 200 |
| Carbon, season with diesel fuel (plot 1.1) | BLOCKED by design: the fuel factors are `null`/PENDING_VERIFICATION, and the app names it a factor-set limitation. The fuel record was not deleted to force a number |
| Carbon, plot 1.2 season (no fuel) | Water regime AWD, pre-season "<180 d dry" and 100 cultivation days were entered through the app's methodology sheet. Harvest 6,400 kg (4 t/ha, same yield as the plot 1.1 seed) on 26/08/2026 was entered through the activity form. Both synced to local Supabase. Calculation: 200 |
| Numeric parity | Backend `total_co2e_kg` 3149.747857, `co2e_per_kg` 0.4921481. The phone shows 3.149,7 kg CO₂e and 0,492 kg CO₂e/kg lúa. A hand calculation from the YAML matches: CH₄ 1.22×0.55×1.00×1.00×100 d×1.6 ha = 107.36 kg ×28 = 3006.08, and N₂O 69 kg N ×0.005 ×44/28 = 0.5421 kg ×265 = 143.67 |
| Duplicate writes | PASS: two more "Tính lại" calls returned 200 and the same `calculation_id`, with 1 row in `carbon_calculations` |
| Calculate with the backend unreachable | PASS: the app says there is no connection and shows the stored result |
| Layout matrix (Home, season detail, resources, carbon, Q&A, sync, account) × portrait/landscape × font 1.0/1.8 | 0 Flutter layout errors and 0 overflow stripes. The stripe detector was validated on the round-1 overflow screenshot |

The carbon screen shows "Hệ thống chưa sẵn sàng tính phát thải CHÍNH THỨC".
This comes from `GET /health` → `carbon_production_ready=false`, which is
derived from the committed factor YAML (domain expert review PENDING, fuel
factors unverified), not from the local DB. Every build of this code shows it,
but it was not checked on hosted because that is out of scope. The numbers
above prove the calculation and display path only. They are reference values,
not MRV evidence.

Device notes: this Xiaomi suppresses `I/flutter` in logcat (`log.tag=M`).
`setprop log.tag.flutter V` was set for the session and is non-persistent.
Every QA setting was restored afterwards (font_scale, rotation, Wi-Fi/data).


## Round 3 — final hardening (14/11/2026)

### Methodology bottom sheet (`season_methodology_sheet.dart`)

Before (`f463aa9`, phone, landscape + Gboard + font 1.8, focus on the days
field): only the days field was visible. Save sat below the keyboard, no
Cancel was visible, and the sheet covered the status bar.

The fix, which applies only while cramped (keyboard open, free height < 260 dp):
- Cancel · title · Save are pinned in a 48 dp row.
- The intro text is hidden.
- `FocusReveal` scrolls the focused field into view.
- The fields keep their keys, so input and focus survive the switch and rotation.

Three defects were found on the phone while verifying it. Each now has a test
that fails without its fix:
- The pinned row sat under the status bar, where Xiaomi swallowed the taps. The
  fix opens the sheet with `useSafeArea: true`.
- The sheet's keyboard padding read `MediaQuery` from the caller's context, so
  the sheet did not rebuild when the keyboard height changed. After a rotation
  it kept a stale inset and slid under the keyboard. This bug predates PR #79.
  The padding now uses the sheet's own context.
- The sheet now draws the same 32x4 drag handle itself, so the handle can be
  dropped while cramped.

Phone results at `8801916`:

| Check | Result |
|---|---|
| Portrait, font 1.0 | PASS: pixel-identical to before (0 of 1,177,200 sheet pixels differ) |
| Landscape + keyboard + font 1.8 | PASS: Huỷ and Lưu at y≈177 px (status bar ends at 100 px, keyboard starts at 382 px); typed value visible; 0 Flutter errors |
| Rotation landscape ↔ portrait | PASS: typed value kept |
| Cancel button (real tap) | PASS: sheet closes on the first tap; DB unchanged |
| System Back | PASS: 1st Back closes the keyboard (sheet back in normal mode, value kept); 2nd Back closes the sheet; DB unchanged |
| Save with invalid value (0) in cramped mode | PASS: the sheet stays open and the field turns red, as in normal mode. Limit: the error text sits under the keyboard until the keyboard is closed |

Screenshots: `E01`/`E02` before; `E03`–`E08` after.

### StatusBadge at 320 dp

At 320×568 with font 1.8, a long StatusBadge label overflowed by 64 px in the
resource dashboard. The badge label now wraps when the width is bounded and
stays content-sized in unbounded rows.

### 320 dp coverage

These are **widget tests with the real Be Vietnam Pro font; there was no
emulator run and no physical 320 dp device.**
- `test/small_screen_320_test.dart`: add-plot form, methodology sheet,
  AppScaffold form and confirmation dialog, at font 1.0/1.8 and with/without a
  simulated 260 dp keyboard (16 cases).
- The carbon and resource screens scroll through 320×568 at font 1.0/1.8. Their
  test files now load the real font; the default test font draws 1 em squares
  and reports false overflows.

### Flaky test (separate Draft PR #80, test-only)

`expired_session_offline_test` › "mất mạng giữa chừng lúc làm mới" raced a
real 10 ms connectivity-debounce Timer against `pumpEventQueue()`.

| Branch | File alone (randomized) | Full suite |
|---|---|---|
| origin/main | 7/30 failed | 2/6 failed |
| PR #79 head | 7/30 failed | 2/6 failed |
| #80 | 0/30 failed | 0/6 failed |

Details are in #80; #79 does not change this test.

### Device and harness notes

- Docker Desktop had exited during the round. It was restarted together with the
  `tec2026-apkqa` stack; data and keys were unchanged.
- `user_rotation` on this Xiaomi sometimes snaps back after a font-scale change.
  The helper now waits until the rotation has held for 3 seconds.
