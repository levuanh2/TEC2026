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

## Fix found on the phone

The add-plot dialog overflowed by 72 px in landscape with the keyboard open at
font scale 1.8. All `AlertDialog`s are now `scrollable: true`, and the shared
dialog theme uses an 8 dp vertical inset. A regression test reproduces the
device geometry: `test/dialog_landscape_keyboard_test.dart` fails with a 75 px
overflow without the fix. In that extreme case the dialog's actions stay
reachable, but the scroll area is about one line tall.

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
