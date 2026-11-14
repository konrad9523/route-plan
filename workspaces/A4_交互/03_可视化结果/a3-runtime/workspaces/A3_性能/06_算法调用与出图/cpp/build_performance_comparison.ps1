$ErrorActionPreference = 'Stop'

$cppDir = $PSScriptRoot
$callsDir = Split-Path -Parent $cppDir
$a3Dir = Split-Path -Parent $callsDir
$workspaceRoot = Split-Path -Parent $a3Dir
# Resolve source directories by required files instead of localized directory
# names. Windows PowerShell can decode UTF-8 path literals with the console
# code page, while file names are stable and are checked below as well.
$bidirectionalCandidates = @(Get-ChildItem -LiteralPath $a3Dir -Directory | Where-Object {
    (Test-Path -LiteralPath (Join-Path $_.FullName 'cpp/bidirectional_astar_received.cpp')) -and
    (Test-Path -LiteralPath (Join-Path $_.FullName 'cpp/bidirectional_astar_variants.cpp')) -and
    (Test-Path -LiteralPath (Join-Path $_.FullName 'cpp/bidirectional_astar_variants.hpp'))
})
if ($bidirectionalCandidates.Count -ne 1) {
    throw "Expected exactly one A3 bidirectional source directory under $a3Dir; found $($bidirectionalCandidates.Count)"
}
$bidirectionalDir = $bidirectionalCandidates[0]
$a2Candidates = @(Get-ChildItem -LiteralPath $workspaceRoot -Directory | Where-Object {
    (Test-Path -LiteralPath (Join-Path $_.FullName 'algorithms.hpp')) -and
    (Test-Path -LiteralPath (Join-Path $_.FullName 'graph_types.hpp'))
})
if ($a2Candidates.Count -ne 1) {
    throw "Expected exactly one A2 header directory under $workspaceRoot; found $($a2Candidates.Count)"
}
$a2Dir = $a2Candidates[0]
$buildDir = Join-Path $env:TEMP 'route_plan_a3_performance_comparison'
$workspaceBuildDir = Join-Path $callsDir '.build'
$workspaceExe = Join-Path $workspaceBuildDir 'performance_comparison.exe'
$vsDevCmd = 'C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat'

if (-not (Test-Path -LiteralPath $vsDevCmd)) {
    throw "Visual Studio developer environment was not found: $vsDevCmd"
}
New-Item -ItemType Directory -Path (Join-Path $buildDir 'include') -Force | Out-Null
New-Item -ItemType Directory -Path $workspaceBuildDir -Force | Out-Null

$sourceFiles = @(
    @{ Source = (Join-Path $cppDir 'performance_comparison.cpp'); Name = 'performance_comparison.cpp' }
    @{ Source = (Join-Path $a3Dir '01_Dijkstra/cpp/dijkstra_cpp.cpp'); Name = 'dijkstra_cpp.cpp' }
    @{ Source = (Join-Path $a3Dir '03_Astar/cpp/astar_cpp.cpp'); Name = 'astar_cpp.cpp' }
    @{ Source = (Join-Path $a3Dir '05_CH/cpp/ch_c_api.cpp'); Name = 'ch_c_api.cpp' }
    @{ Source = (Join-Path $a3Dir '05_CH/cpp/ch.cpp'); Name = 'ch.cpp' }
    @{ Source = (Join-Path $bidirectionalDir.FullName 'cpp/bidirectional_astar_received.cpp'); Name = 'bidirectional_astar_received.cpp' }
    @{ Source = (Join-Path $bidirectionalDir.FullName 'cpp/bidirectional_astar_variants.cpp'); Name = 'bidirectional_astar_variants.cpp' }
    @{ Source = (Join-Path $bidirectionalDir.FullName 'cpp/bidirectional_astar_variants.hpp'); Name = 'bidirectional_astar_variants.hpp' }
    @{ Source = (Join-Path $a2Dir.FullName 'algorithms.hpp'); Name = 'algorithms.hpp' }
    @{ Source = (Join-Path $a2Dir.FullName 'graph_types.hpp'); Name = 'graph_types.hpp' }
)
foreach ($file in $sourceFiles) {
    if (-not (Test-Path -LiteralPath $file.Source)) {
        throw "C++ source was not found: $($file.Source)"
    }
    $destination = if ($file.Name.EndsWith('.hpp')) {
        Join-Path $buildDir 'include'
    } else {
        $buildDir
    }
    Copy-Item -LiteralPath $file.Source -Destination (Join-Path $destination $file.Name) -Force
}

$batch = @'
@echo off
call "C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat" -arch=x64 -host_arch=x64 >nul
if errorlevel 1 exit /b %errorlevel%
cd /d "%~dp0"
cl.exe /nologo /std:c++17 /EHsc /utf-8 /W4 /O2 /DNDEBUG /I include /Fe:performance_comparison.exe performance_comparison.cpp dijkstra_cpp.cpp astar_cpp.cpp ch_c_api.cpp ch.cpp bidirectional_astar_received.cpp bidirectional_astar_variants.cpp
exit /b %errorlevel%
'@
$buildScript = Join-Path $buildDir 'build_performance_comparison.cmd'
Set-Content -LiteralPath $buildScript -Value $batch -Encoding ascii
& $buildScript
if ($LASTEXITCODE -ne 0) {
    throw "C++ performance comparison build failed: $LASTEXITCODE"
}
Copy-Item -LiteralPath (Join-Path $buildDir 'performance_comparison.exe') -Destination $workspaceExe -Force
Write-Output $workspaceExe
