# Flutter visual refresh — 2026-11-12

## Scope

Flutter now shares the AgriCarbon web palette, bundled Be Vietnam Pro font,
rice-field artwork and the team slogan **Số hóa canh tác - Xanh hóa tương lai**.
This changes presentation only. Authentication callbacks, API clients, local
database, offline queue, synchronization, Carbon calculations and CV inference
remain unchanged. The React public website work is separate.

- Login has an original rice-field composition, a white form panel and a
  responsive layout (stacked on phones, two columns on wider screens).
- Shared screens inherit the green-to-blue background, dark green headers,
  updated cards, form controls, sheets, dialogs and navigation.
- Home adds the brand banner. Quick actions use distinct water, earth and
  information colors. Resource metrics use corresponding domain colors.
- Quick-action columns adapt to available width and enlarged text.
- Short entrance/route fades respect the device's disable-animations setting.
  iOS/macOS retain Flutter's default route transitions.

## Assets

`app/assets/images/mekong-rice.webp` is the same original generated image used
by the web redesign. It depicts a flat Mekong rice landscape, not farm evidence.
Be Vietnam Pro weights 400/500/600/700/800 come from the Google Fonts repository
(`ofl/bevietnampro`), under the bundled `app/assets/fonts/OFL.txt` license.
Fonts and artwork are packaged with the app and need no runtime download.
No package versions were changed in the app's dependency lockfile.

## Verification

- `flutter analyze --no-pub`: PASS, no issues.
- Full Flutter suite: **483/483 PASS**.
- Dedicated visual suite: **10/10 PASS**, including screenshot export.
- Local Flutter web preview build: PASS. Browser load: 0 JavaScript page errors.
- Android debug build was started, including CMake installation; no completed
  APK was available when preparing publication. This is not reported as a pass.

The visual tests load the actual bundled typefaces and Material Icons. Login
is checked at 320×568, 390×844, 430×932 and 800×1200, at text scales 1.0 and
1.5. Additional checks cover Home scrolling and camera shortcut dispatch,
and shared inputs at text scale 1.8 with reduced motion. Optional screenshots
are written to ignored `app/build/ui-refresh/`:

```powershell
cd app
flutter test test/visual_refresh_test.dart --reporter expanded --dart-define=UI_SCREENSHOTS=true
```

No Android device or emulator is available in this session, so widget
screenshots and browser preview do not establish device-level acceptance.
No live account, hosted data or external service was modified for these checks.

## Local interactive preview

The preview imports the actual LoginScreen, HomeTab and shared Flutter widgets.
Its fixtures live only in `app/tool/ui_preview.dart`, outside production `lib/`.
The entry is never imported by `lib/main.dart`. It initializes no Supabase,
network client, database or sync engine. Its top bar explicitly labels the
content as preview data; Carbon/resource values remain absent.

Generate the ignored web wrapper and build:

```powershell
cd app
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tool/prepare_ui_preview.ps1
python -m http.server 5180 --bind 127.0.0.1 --directory build/ui_preview/build/web
```

Open <http://127.0.0.1:5180/>. Use the menu at the top right to select login,
Home or shared components. The bottom navigation demonstrates selection;
preview actions display a local message and do not perform real writes.
This wrapper stays under `build/` and does not enable a new production platform.

The subsequent user request authorizes commit/push of all completed web and
Flutter interface changes to `ui/agricarbon-web-flutter-2026-11-12`.
Release signing and deployment are outside this publication scope.
