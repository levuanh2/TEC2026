param()

$ErrorActionPreference = 'Stop'
$appRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$previewRoot = Join-Path $appRoot 'build/ui_preview'

# This wrapper stays in ignored build/. It does not enable web in the app.
Push-Location $appRoot
try {
    flutter create --platforms=web --project-name=agricarbon_ui_preview --no-pub build/ui_preview
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the UI preview wrapper.' }

    $utf8 = New-Object System.Text.UTF8Encoding($false)
    $appSpec = [System.IO.File]::ReadAllText((Join-Path $appRoot 'pubspec.yaml'))
    $presentationSpec = [regex]::Match($appSpec, '(?ms)^flutter:\s*\r?\n.*$').Value
    if (-not $presentationSpec) { throw 'Missing Flutter assets/fonts manifest.' }
    $previewSpec = @'
name: agricarbon_ui_preview
publish_to: none
environment:
  sdk: '>=3.13.0 <4.0.0'
dependencies:
  flutter:
    sdk: flutter
  flutter_localizations:
    sdk: flutter
  agricarbon_app:
    path: ../..

'@
    [System.IO.File]::WriteAllText((Join-Path $previewRoot 'pubspec.yaml'),
        $previewSpec + "`n" + $presentationSpec, $utf8)
    Copy-Item -LiteralPath (Join-Path $appRoot 'assets') -Destination $previewRoot -Recurse -Force
    Copy-Item -LiteralPath (Join-Path $appRoot 'pubspec.lock') -Destination $previewRoot -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'ui_preview.dart') -Destination (Join-Path $previewRoot 'lib/ui_preview.dart') -Force
    [System.IO.File]::WriteAllText((Join-Path $previewRoot 'lib/main.dart'),
        "import 'ui_preview.dart' as preview;`nvoid main() => preview.main();`n", $utf8)

    Push-Location $previewRoot
    try {
        flutter build web --no-web-resources-cdn
        if ($LASTEXITCODE -ne 0) { throw 'Could not build the UI preview.' }
    } finally { Pop-Location }
} finally { Pop-Location }

Write-Output "UI preview ready: $previewRoot/build/web"
Write-Output 'Serve this folder on localhost. The preview uses no real account or storage.'
