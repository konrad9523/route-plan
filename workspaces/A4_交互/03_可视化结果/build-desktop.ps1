$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = if (Test-Path -LiteralPath 'E:\app\python\python.exe') { 'E:\app\python\python.exe' } else { 'python' }
$build = Join-Path $root 'desktop-build'
$release = Join-Path $root 'desktop-release'
$nativeBuild = Join-Path $root '.a3-route-build'

# Build the A3 single-route DLLs before packaging.  The navigation backend
# loads these files through ctypes; omitting one here makes only the affected
# algorithm fail at runtime while the rest of the desktop app still opens.
$vsRoot = Join-Path ${env:ProgramFiles} 'Microsoft Visual Studio\2022\Community'
$vcvars = Join-Path $vsRoot 'VC\Auxiliary\Build\vcvars64.bat'
if (-not (Test-Path -LiteralPath $vcvars)) {
  throw "Visual C++ build environment not found: $vcvars"
}
New-Item -ItemType Directory -Path $nativeBuild -Force | Out-Null
$a3WorkspaceRoot = Join-Path $root 'a3-runtime\workspaces'
$a3Root = (Get-ChildItem -LiteralPath $a3WorkspaceRoot -Directory |
  Where-Object { $_.Name -like 'A3_*' } | Select-Object -First 1).FullName
if (-not $a3Root) { throw "A3 workspace not found under $a3WorkspaceRoot" }
$a2Root = (Get-ChildItem -LiteralPath $a3WorkspaceRoot -Directory |
  Where-Object { $_.Name -like 'A2_*' } | Select-Object -First 1).FullName
if (-not $a2Root) { throw "A2 workspace not found under $a3WorkspaceRoot" }
# cl.exe is launched through cmd.exe below.  Its legacy command-line code
# page cannot reliably open the Chinese project path, so stage just the C++
# sources and shared headers in an ASCII temporary directory first.
$nativeSource = Join-Path $env:TEMP 'G4A3RouteNative'
if (Test-Path -LiteralPath $nativeSource) { Remove-Item -LiteralPath $nativeSource -Recurse -Force }
New-Item -ItemType Directory -Path $nativeSource -Force | Out-Null
$biWorkspace = Get-ChildItem -LiteralPath $a3Root -Directory |
  Where-Object { $_.Name -like '04_*' } | Select-Object -First 1
if (-not $biWorkspace) { throw "A3 bidirectional A* workspace not found under $a3Root" }
$biCpp = Join-Path $biWorkspace.FullName 'cpp'
foreach ($source in @(
  (Join-Path $biCpp 'a4_bidirectional_astar_c_api.cpp'),
  (Join-Path $biCpp 'bidirectional_astar_variants.cpp'),
  (Join-Path $biCpp 'bidirectional_astar_received.cpp'),
  (Join-Path $biCpp 'bidirectional_astar_variants.hpp'),
  (Join-Path $a2Root 'algorithms.hpp'),
  (Join-Path $a2Root 'graph_types.hpp')
)) {
  Copy-Item -LiteralPath $source -Destination $nativeSource -Force
}
$biObjects = @(
  (Join-Path $nativeBuild 'bidirectional_astar_c_api.obj')
  (Join-Path $nativeBuild 'bidirectional_astar_variants.obj')
  (Join-Path $nativeBuild 'bidirectional_astar_received.obj')
)
$biSources = @(
  (Join-Path $nativeSource 'a4_bidirectional_astar_c_api.cpp')
  (Join-Path $nativeSource 'bidirectional_astar_variants.cpp')
  (Join-Path $nativeSource 'bidirectional_astar_received.cpp')
)
for ($i = 0; $i -lt $biSources.Count; $i++) {
  $compile = '"{0}" && cl.exe /nologo /std:c++17 /EHsc /utf-8 /W4 /O2 /DNDEBUG /c /I"{1}" /I"{2}" /Fo"{3}" "{4}"' -f `
  $vcvars, $nativeSource, $nativeSource, $biObjects[$i], $biSources[$i]
  cmd.exe /d /s /c $compile
  if ($LASTEXITCODE -ne 0) { throw "Failed to compile A3 bidirectional A* source: $($biSources[$i])" }
}
$biDll = Join-Path $nativeBuild 'bidirectional_astar_cpp.dll'
# link.exe still uses a legacy code page for its output path. Link in the
# ASCII temp directory first, then copy the finished DLL into the project.
$nativeDllTemp = Join-Path $nativeSource 'bidirectional_astar_cpp.dll'
$link = '"{0}" && link.exe /NOLOGO /DLL /OUT:"{1}" "{2}" "{3}" "{4}"' -f `
  $vcvars, $nativeDllTemp, $biObjects[0], $biObjects[1], $biObjects[2]
cmd.exe /d /s /c $link
if ($LASTEXITCODE -ne 0) { throw 'Failed to link A3 bidirectional A* DLL' }
Copy-Item -LiteralPath $nativeDllTemp -Destination $biDll -Force

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
