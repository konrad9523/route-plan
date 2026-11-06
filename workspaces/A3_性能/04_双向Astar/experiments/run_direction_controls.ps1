param([switch]$BuildOnly)

$ErrorActionPreference = 'Stop'

$experimentRoot = $PSScriptRoot
$repoRoot = (Resolve-Path (Join-Path $experimentRoot '../../../..')).Path
$resultRoot = Join-Path $repoRoot 'workspaces/A3_性能/07_实验结果/双向Astar/direction_control_2026-11-04'

$buildRoot = Join-Path $env:TEMP ('route_biastar_controls_' + [guid]::NewGuid().ToString('N'))
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
    (Join-Path $repoRoot 'workspaces/A3_性能/04_双向Astar/tests/bidirectional_astar_cpp_smoke.cpp'), `
    (Join-Path $repoRoot 'workspaces/A3_性能/04_双向Astar/experiments/benchmark_search_optimizations.cpp') `
    -Destination (Join-Path $buildRoot 'tests')
Copy-Item -LiteralPath (Join-Path $buildRoot 'tests/bidirectional_astar_cpp_smoke.cpp') `
    -Destination (Join-Path $buildRoot 'tests/smoke.cpp')
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
cl.exe /nologo /std:c++17 /EHsc /utf-8 /W4 /O2 /DNDEBUG /I include /Fe:benchmark_search.exe tests\benchmark_search_optimizations.cpp cpp\bidirectional_astar_received.cpp cpp\bidirectional_astar_variants.cpp
exit /b %errorlevel%
'@
$buildScript = Join-Path $buildRoot 'build.cmd'
Set-Content -LiteralPath $buildScript -Value $batch -Encoding ascii
& $buildScript 2>&1 | Tee-Object -FilePath (Join-Path $buildRoot 'build_and_correctness.log')
if ($LASTEXITCODE -ne 0) { throw "C++ build or correctness check failed: $LASTEXITCODE" }
if ($BuildOnly) {
    Write-Host "Build and correctness smoke test passed. Artifacts: $buildRoot"
    return
}
if (Test-Path -LiteralPath $resultRoot) {
    throw "Refusing to overwrite existing result directory: $resultRoot"
}
New-Item -ItemType Directory -Path $resultRoot | Out-Null
Copy-Item -LiteralPath (Join-Path $buildRoot 'build_and_correctness.log') `
    -Destination (Join-Path $resultRoot 'build_and_correctness.log')

$networks = @(
    @{ Name = 'nanshan'; File = 'nanshan_driving_a1_fixed.graphml' },
    @{ Name = 'shenzhen'; File = 'shenzhen_driving_a1_fixed.graphml' },
    @{ Name = 'guangdong'; File = 'guangdong_driving_a1_fixed.graphml' }
)
$manifestPath = Join-Path $repoRoot 'data/a3_network_manifest.json'
$networkManifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding utf8 | ConvertFrom-Json
$converter = Join-Path $experimentRoot 'prepare_graphml.py'
$runner = Join-Path $buildRoot 'benchmark_search.exe'
$previousResults = Join-Path $repoRoot 'workspaces/A3_性能/07_实验结果/双向Astar/paper_layers_2026-11-03'
$runLog = [System.Collections.Generic.List[string]]::new()
$runLog.Add("Date: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss K')")
$runLog.Add("OS: $([Environment]::OSVersion.VersionString)")
$runLog.Add("Architecture: $([Runtime.InteropServices.RuntimeInformation]::OSArchitecture)")
$cpuName = (Get-ItemProperty 'HKLM:\HARDWARE\DESCRIPTION\System\CentralProcessor\0' -Name ProcessorNameString).ProcessorNameString
$runLog.Add("CPU: $cpuName ($env:NUMBER_OF_PROCESSORS logical processors)")
$runLog.Add('Compiler: MSVC 2022 Community; C++17 /O2 /DNDEBUG /W4; correctness executable /Od')
$runLog.Add('Control experiment: H0 only; same 100 fixed queries per network; 5 randomized paired rounds; all route costs and edge paths validated')
$runLog.Add('Stop-policy comparison: L4 native 1e-12 tolerance versus strict L4 lower bound; L1 uses its existing strict bound')
$runLog.Add('Direction comparison: native min reduced key versus alternating forward/backward; L4 min-key control uses algebraically normalized b keys')

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
    $runLog.Add("Graph SHA-256 ($($network.Name)): $actualHash")

    $sourceQueries = Join-Path $previousResults ($network.Name + '_queries.csv')
    if (-not (Test-Path -LiteralPath $sourceQueries)) {
        throw "Fixed query set is missing: $sourceQueries"
    }
    $queryHash = (Get-FileHash -LiteralPath $sourceQueries -Algorithm SHA256).Hash.ToUpperInvariant()
    $queryCopy = Join-Path $resultRoot ($network.Name + '_queries.csv')
    Copy-Item -LiteralPath $sourceQueries -Destination $queryCopy
    $runLog.Add("Fixed query SHA-256 ($($network.Name)): $queryHash")

    $binary = Join-Path $buildRoot ($network.Name + '.bin')
    $convertLog = Join-Path $resultRoot ($network.Name + '_conversion.log')
    $convertOutput = & python $converter $graphml $binary 2>&1
    $convertOutput | Tee-Object -FilePath $convertLog
    if ($LASTEXITCODE -ne 0) { throw "GraphML conversion failed for $($network.Name)" }

    $rawTmp = Join-Path $buildRoot ($network.Name + '_raw.csv')
    $queryTmp = Join-Path $buildRoot ($network.Name + '_queries.csv')
    $preprocessTmp = Join-Path $buildRoot ($network.Name + '_preprocess.csv')
    $landmarksTmp = Join-Path $buildRoot ($network.Name + '_landmarks.csv')
    Copy-Item -LiteralPath $queryCopy -Destination $queryTmp
    $benchmarkLog = Join-Path $resultRoot ($network.Name + '_benchmark.log')
    $benchmarkOutput = & $runner $binary $network.Name $rawTmp $queryTmp $preprocessTmp $landmarksTmp controls 2>&1
    $benchmarkOutput | Tee-Object -FilePath $benchmarkLog
    if ($LASTEXITCODE -ne 0) { throw "Direction-control benchmark failed for $($network.Name)" }

    Copy-Item -LiteralPath $rawTmp -Destination (Join-Path $resultRoot ($network.Name + '_raw.csv'))
    Copy-Item -LiteralPath $preprocessTmp -Destination (Join-Path $resultRoot ($network.Name + '_preprocess.csv'))
    Copy-Item -LiteralPath $landmarksTmp -Destination (Join-Path $resultRoot ($network.Name + '_landmarks.csv'))
    foreach ($line in $benchmarkOutput) { $runLog.Add([string]$line) }
}

$runLog | Set-Content -LiteralPath (Join-Path $resultRoot 'run.log') -Encoding utf8
$summarizer = Join-Path $experimentRoot 'summarize_direction_controls.py'
& python $summarizer $resultRoot
if ($LASTEXITCODE -ne 0) { throw 'Direction-control summary generation failed' }

Write-Host "Results saved under: $resultRoot"
