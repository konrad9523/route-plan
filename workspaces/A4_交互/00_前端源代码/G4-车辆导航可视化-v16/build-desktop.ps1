$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = if (Test-Path -LiteralPath 'E:\app\python\python.exe') { 'E:\app\python\python.exe' } else { 'python' }
$build = Join-Path $root 'desktop-build'
$release = Join-Path $root 'desktop-release'

if (Test-Path -LiteralPath $build) { Remove-Item -LiteralPath $build -Recurse -Force }
if (Test-Path -LiteralPath $release) { Remove-Item -LiteralPath $release -Recurse -Force }

& $python -m PyInstaller --noconfirm --clean --onedir --windowed `
  --name G4VehicleNavigation --distpath $build --workpath (Join-Path $build 'work') `
  --specpath (Join-Path $build 'spec') (Join-Path $root 'desktop_app.py')

$app = Join-Path $build 'G4VehicleNavigation'
New-Item -ItemType Directory -Path $release -Force | Out-Null
Copy-Item -Path (Join-Path $app '*') -Destination $release -Recurse -Force

foreach ($name in @('index.html','app.js','styles.css','api-config.js','a2-api.js','a3-api.js','ch-api.js','ch-replay.js','performance-dashboard.js','server.py','a3_route_backend.py','a3_server.py','README.md')) {
  Copy-Item -LiteralPath (Join-Path $root $name) -Destination $release -Force
}
Get-ChildItem -LiteralPath $root -Filter '*.txt' -File | Copy-Item -Destination $release -Force
foreach ($dir in @('assets','data','mock','tools','a3-runtime')) {
  Copy-Item -LiteralPath (Join-Path $root $dir) -Destination $release -Recurse -Force
}

Copy-Item -LiteralPath (Join-Path $root 'a2-runtime') -Destination $release -Recurse -Force
if (Test-Path -LiteralPath (Join-Path $root '.a3-route-build')) {
  Copy-Item -LiteralPath (Join-Path $root '.a3-route-build') -Destination $release -Recurse -Force
}

# Bundle the prepared Guangdong CH index. The desktop shell copies it to an
# ASCII temp directory before starting the server because the shipped C ABI
# cannot open a Chinese absolute path through its legacy char* parameter.
$chCacheSource = Join-Path $env:TEMP 'G4RouteCache\g4-guangdong-ch.cache'
$chCacheTarget = Join-Path $release 'data\ch-cache'
if (Test-Path -LiteralPath $chCacheSource) {
  New-Item -ItemType Directory -Path $chCacheTarget -Force | Out-Null
  Copy-Item -LiteralPath $chCacheSource -Destination $chCacheTarget -Force
} else {
  Write-Warning "CH cache not found at $chCacheSource; the CH route option will require offline preprocessing."
}

# Keep Python beside the executable so the recipient does not need E:\app or
# a system Python installation. The runtime is large, but it makes the package
# independent of the developer machine.
$pythonTarget = Join-Path $release 'runtime\python'
New-Item -ItemType Directory -Path $pythonTarget -Force | Out-Null
$robocopy = Start-Process -FilePath 'robocopy.exe' -ArgumentList @(
  'E:\app\python', $pythonTarget, '/E', '/XD', '__pycache__', '.pytest_cache',
  '/NFL', '/NDL', '/NJH', '/NJS', '/NP'
) -Wait -PassThru -NoNewWindow
if ($robocopy.ExitCode -gt 7) { throw "Python runtime copy failed: $($robocopy.ExitCode)" }

$graphmlDir = Join-Path $release 'data\graphml'
New-Item -ItemType Directory -Path $graphmlDir -Force | Out-Null
Set-Content -LiteralPath (Join-Path $graphmlDir 'README.txt') -Value @(
  'This desktop package uses prepared A2/A3 caches; raw GraphML is optional.',
  'To rebuild caches, place the three GraphML files here and disable cache-only mode.'
) -Encoding UTF8

Set-Content -LiteralPath (Join-Path $release 'Start-G4.bat') -Value @(
  '@echo off',
  'cd /d "%~dp0"',
  'start "" "%~dp0G4VehicleNavigation.exe"'
) -Encoding ASCII
Write-Host "Portable desktop package built: $release"
