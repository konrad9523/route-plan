$ErrorActionPreference = 'Stop'

$experimentRoot = $PSScriptRoot
$repoRoot = (Resolve-Path (Join-Path $experimentRoot '../../../..')).Path
$resultRoot = Join-Path $repoRoot 'workspaces/A3_性能/07_实验结果/双向Astar/paper_layers_2026-11-03'
if (Test-Path -LiteralPath $resultRoot) {
    throw "Refusing to overwrite existing result directory: $resultRoot"
}
New-Item -ItemType Directory -Path $resultRoot | Out-Null

$buildRoot = Join-Path $env:TEMP ('route_biastar_' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path `
    (Join-Path $buildRoot 'include'), `
    (Join-Path $buildRoot 'cpp'), `
    (Join-Path $buildRoot 'tests'), `
    (Join-Path $buildRoot 'experiments') | Out-Null

Copy-Item -LiteralPath `
    (Join-Path $repoRoot 'workspaces/A3_性能/04_双向Astar/cpp/bidirectional_astar_variants.hpp'), `
    (Join-Path $repoRoot 'workspaces/A3_性能/04_双向Astar/cpp/bidirectional_astar_variants.cpp'), `
    (Join-Path $repoRoot 'workspaces/A3_性能/04_双向Astar/cpp/bidirectional_astar_received.cpp') `
    -Destination (Join-Path $buildRoot 'cpp')
Copy-Item -LiteralPath `
    (Join-Path $repoRoot 'workspaces/A3_性能/04_双向Astar/tests/bidirectional_astar_cpp_smoke.cpp') `
    -Destination (Join-Path $buildRoot 'tests/smoke.cpp')
Copy-Item -LiteralPath `
    (Join-Path $repoRoot 'workspaces/A3_性能/04_双向Astar/experiments/benchmark.cpp') `
    -Destination (Join-Path $buildRoot 'experiments/benchmark.cpp')
Copy-Item -LiteralPath `
    (Join-Path $repoRoot 'workspaces/A2_算法/algorithms.hpp'), `
    (Join-Path $repoRoot 'workspaces/A2_算法/graph_types.hpp') `
    -Destination (Join-Path $buildRoot 'include')

$vsDevCmd = 'C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat'
if (-not (Test-Path -LiteralPath $vsDevCmd)) {
    throw "Visual Studio developer environment was not found: $vsDevCmd"
}
$batch = @'
@echo off
call "C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat" -arch=x64 -host_arch=x64 >nul
cd /d "%~dp0"
cl.exe /nologo /std:c++17 /EHsc /utf-8 /W4 /Od /I include /Fe:smoke.exe tests\smoke.cpp cpp\bidirectional_astar_received.cpp cpp\bidirectional_astar_variants.cpp
if errorlevel 1 exit /b %errorlevel%
smoke.exe
if errorlevel 1 exit /b %errorlevel%
cl.exe /nologo /std:c++17 /EHsc /utf-8 /W4 /O2 /DNDEBUG /I include /Fe:benchmark.exe experiments\benchmark.cpp cpp\bidirectional_astar_received.cpp cpp\bidirectional_astar_variants.cpp
if errorlevel 1 exit /b %errorlevel%
'@
$buildScript = Join-Path $buildRoot 'build.cmd'
Set-Content -LiteralPath $buildScript -Value $batch -Encoding ascii
& $buildScript 2>&1 | Tee-Object -FilePath (Join-Path $resultRoot 'build.log')
if ($LASTEXITCODE -ne 0) { throw "C++ build or smoke check failed with exit code $LASTEXITCODE" }

$networks = @(
    @{ Name = 'nanshan'; File = 'nanshan_driving_a1_fixed.graphml' },
    @{ Name = 'shenzhen'; File = 'shenzhen_driving_a1_fixed.graphml' },
    @{ Name = 'guangdong'; File = 'guangdong_driving_a1_fixed.graphml' }
)
$manifestPath = Join-Path $repoRoot 'data/a3_network_manifest.json'
$networkManifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding utf8 | ConvertFrom-Json
$converter = Join-Path $experimentRoot 'prepare_graphml.py'
$runner = Join-Path $buildRoot 'benchmark.exe'
$runLog = Join-Path $resultRoot 'run.log'
$runLogLines = [System.Collections.Generic.List[string]]::new()
$runLogLines.Add("Date: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss K')")
$runLogLines.Add("OS: $([Environment]::OSVersion.VersionString)")
$runLogLines.Add("Architecture: $([Runtime.InteropServices.RuntimeInformation]::OSArchitecture)")
$cpuName = (Get-ItemProperty 'HKLM:\HARDWARE\DESCRIPTION\System\CentralProcessor\0' -Name ProcessorNameString).ProcessorNameString
$runLogLines.Add("CPU: $cpuName ($env:NUMBER_OF_PROCESSORS logical processors)")
$runLogLines.Add("Compiler: MSVC 2022 Community; /std:c++17 /O2 /DNDEBUG /W4")
$runLogLines.Add('Timing: std::chrono::steady_clock around one complete algorithm call, including path reconstruction')
$runLogLines.Add('Policy: 100 fixed queries in the largest SCC per graph; 5 rounds; shuffled query and layer order')
$runLogLines.Add('Heuristic: common scaled spherical-chord H0; ALT excluded to isolate search-policy changes')

foreach ($network in $networks) {
    $graphml = Join-Path $repoRoot ('data/' + $network.File)
    if (-not (Test-Path -LiteralPath $graphml)) {
        throw "Road graph was not found: $graphml"
    }
    $manifestEntry = $networkManifest.files | Where-Object filename -eq $network.File
    if ($null -eq $manifestEntry) { throw "Graph is missing from the A3 manifest: $($network.File)" }
    $actualHash = (Get-FileHash -LiteralPath $graphml -Algorithm SHA256).Hash.ToUpperInvariant()
    if ($actualHash -ne $manifestEntry.sha256) {
        throw "Graph SHA-256 does not match the A3 manifest: $($network.File)"
    }
    $runLogLines.Add("Graph SHA-256 ($($network.Name)): $actualHash")
    $binary = Join-Path $buildRoot ($network.Name + '.bin')
    $raw = Join-Path $resultRoot ($network.Name + '_raw.csv')
    $queries = Join-Path $resultRoot ($network.Name + '_queries.csv')
    $runLogLines.Add("--- $($network.Name) ---")

    $convertOutput = & python $converter $graphml $binary 2>&1
    $convertOutput | Tee-Object -FilePath (Join-Path $resultRoot ($network.Name + '_conversion.log'))
    if ($LASTEXITCODE -ne 0) { throw "GraphML conversion failed for $($network.Name)" }

    $benchmarkOutput = & $runner $binary $network.Name $raw $queries 100 2>&1
    $benchmarkOutput | Tee-Object -FilePath (Join-Path $resultRoot ($network.Name + '_benchmark.log'))
    if ($LASTEXITCODE -ne 0) { throw "Benchmark failed for $($network.Name)" }
    foreach ($line in $benchmarkOutput) { $runLogLines.Add([string]$line) }
}

$runLogLines | Set-Content -LiteralPath $runLog -Encoding utf8
$summarizer = Join-Path $experimentRoot 'summarize.py'
$rawFiles = Get-ChildItem -LiteralPath $resultRoot -Filter '*_raw.csv' | ForEach-Object FullName
& python $summarizer (Join-Path $resultRoot 'summary.csv') @rawFiles
if ($LASTEXITCODE -ne 0) { throw 'Summary generation failed' }

Write-Host "Results saved under: $resultRoot"
