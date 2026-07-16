param(
    [string]$UnityPath = "C:\Program Files\Unity\Hub\Editor\6000.3.15f1\Editor\Unity.exe",
    [string]$MC2Path = "D:\Unity_Fork\MagicaCloth2",
    [string]$OutputDirectory = ""
)

$ErrorActionPreference = "Stop"
$ExpectedCommit = "418f89ff31a45bb4b2336641ad5907a1110eabea"
$ProjectPath = $PSScriptRoot

if (-not (Test-Path -LiteralPath $UnityPath)) {
    throw "Unity executable not found: $UnityPath"
}
if (-not (Test-Path -LiteralPath $MC2Path)) {
    throw "MC2 checkout not found: $MC2Path"
}

$ActualCommit = (& git -c "safe.directory=$MC2Path" -C $MC2Path rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $ActualCommit -ne $ExpectedCommit) {
    throw "MC2 commit mismatch. Expected $ExpectedCommit, got $ActualCommit"
}

$ManifestPath = Join-Path $ProjectPath "Packages\manifest.json"
$Manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
$ManifestMC2Path = $Manifest.dependencies.'com.magicasoft.magica-cloth2'
$ExpectedMC2Path = "file:" + $MC2Path.Replace("\", "/")
if ($ManifestMC2Path -ne $ExpectedMC2Path) {
    throw "manifest MC2 path mismatch. Expected $ExpectedMC2Path, got $ManifestMC2Path"
}

if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $ProjectPath "..\..\OmniNode\NodeTree\Function\physicsWorld\mc2\test\fixtures\tier_a"
}
$OutputDirectory = [System.IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$LogDirectory = Join-Path $ProjectPath "Logs"
$LogPath = Join-Path $LogDirectory "oracle.log"
New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null

$StartedAtUtc = [DateTime]::UtcNow
$UnityArguments = @(
    "-batchmode",
    "-nographics",
    "--burst-disable-compilation",
    "-quit",
    "-projectPath", "`"$ProjectPath`"",
    "-logFile", "`"$LogPath`"",
    "-executeMethod", "HoTools.MC2Oracle.Editor.MC2MeshBaselineOracle.RunBatch",
    "-mc2OracleOutput", "`"$OutputDirectory`""
)
$UnityProcess = Start-Process `
    -FilePath $UnityPath `
    -ArgumentList $UnityArguments `
    -WindowStyle Hidden `
    -Wait `
    -PassThru

if ($UnityProcess.ExitCode -ne 0) {
    throw "Unity oracle failed with exit code $($UnityProcess.ExitCode). See $LogPath"
}

$FixtureCount = @(
    Get-ChildItem -LiteralPath $OutputDirectory -Filter "mesh_baseline_*.json" -File |
        Where-Object { $_.LastWriteTimeUtc -ge $StartedAtUtc }
).Count
if ($FixtureCount -ne 9) {
    throw "Unity oracle produced $FixtureCount fixtures instead of 9. See $LogPath"
}

$ProxyFixtureCount = @(
    Get-ChildItem -LiteralPath $OutputDirectory -Filter "mesh_proxy_*.json" -File |
        Where-Object { $_.LastWriteTimeUtc -ge $StartedAtUtc }
).Count
if ($ProxyFixtureCount -ne 8) {
    throw "Unity oracle produced $ProxyFixtureCount proxy fixtures instead of 8. See $LogPath"
}

$DistanceFixtureCount = @(
    Get-ChildItem -LiteralPath $OutputDirectory -Filter "distance_*.json" -File |
        Where-Object { $_.Name -notlike "distance_runtime_*" } |
        Where-Object { $_.LastWriteTimeUtc -ge $StartedAtUtc }
).Count
if ($DistanceFixtureCount -ne 7) {
    throw "Unity oracle produced $DistanceFixtureCount distance fixtures instead of 7. See $LogPath"
}

$DistanceRuntimeFixtureCount = @(
    Get-ChildItem -LiteralPath $OutputDirectory -Filter "distance_runtime_*.json" -File |
        Where-Object { $_.LastWriteTimeUtc -ge $StartedAtUtc }
).Count
if ($DistanceRuntimeFixtureCount -ne 2) {
    throw "Unity oracle produced $DistanceRuntimeFixtureCount distance runtime fixtures instead of 2. See $LogPath"
}

$BendingFixtureCount = @(
    Get-ChildItem -LiteralPath $OutputDirectory -Filter "bending_*.json" -File |
        Where-Object { $_.Name -notlike "bending_runtime_*" } |
        Where-Object { $_.LastWriteTimeUtc -ge $StartedAtUtc }
).Count
if ($BendingFixtureCount -ne 13) {
    throw "Unity oracle produced $BendingFixtureCount bending fixtures instead of 13. See $LogPath"
}

$BendingRuntimeFixtureCount = @(
    Get-ChildItem -LiteralPath $OutputDirectory -Filter "bending_runtime_*.json" -File |
        Where-Object { $_.LastWriteTimeUtc -ge $StartedAtUtc }
).Count
if ($BendingRuntimeFixtureCount -ne 3) {
    throw "Unity oracle produced $BendingRuntimeFixtureCount bending runtime fixtures instead of 3. See $LogPath"
}

$RuntimeParameterFixtureCount = @(
    Get-ChildItem -LiteralPath $OutputDirectory -Filter "runtime_parameters_*.json" -File |
        Where-Object { $_.LastWriteTimeUtc -ge $StartedAtUtc }
).Count
if ($RuntimeParameterFixtureCount -ne 2) {
    throw "Unity oracle produced $RuntimeParameterFixtureCount runtime parameter fixtures instead of 2. See $LogPath"
}

$FrameResetFixtureCount = @(
    Get-ChildItem -LiteralPath $OutputDirectory -Filter "frame_reset_*.json" -File |
        Where-Object { $_.LastWriteTimeUtc -ge $StartedAtUtc }
).Count
if ($FrameResetFixtureCount -ne 1) {
    throw "Unity oracle produced $FrameResetFixtureCount frame/reset fixtures instead of 1. See $LogPath"
}

$CenterFixtureCount = @(
    Get-ChildItem -LiteralPath $OutputDirectory -Filter "center_static_*.json" -File |
        Where-Object { $_.LastWriteTimeUtc -ge $StartedAtUtc }
).Count
if ($CenterFixtureCount -ne 1) {
    throw "Unity oracle produced $CenterFixtureCount center fixtures instead of 1. See $LogPath"
}

$CenterStepFixtureCount = @(
    Get-ChildItem -LiteralPath $OutputDirectory -Filter "center_step_*.json" -File |
        Where-Object { $_.LastWriteTimeUtc -ge $StartedAtUtc }
).Count
if ($CenterStepFixtureCount -ne 1) {
    throw "Unity oracle produced $CenterStepFixtureCount center-step fixtures instead of 1. See $LogPath"
}

$CenterFrameShiftFixtureCount = @(
    Get-ChildItem -LiteralPath $OutputDirectory -Filter "center_frame_shift_*.json" -File |
        Where-Object { $_.LastWriteTimeUtc -ge $StartedAtUtc }
).Count
if ($CenterFrameShiftFixtureCount -ne 14) {
    throw "Unity oracle produced $CenterFrameShiftFixtureCount center-frame-shift fixtures instead of 14. See $LogPath"
}

$ParticleStepFixtureCount = @(
    Get-ChildItem -LiteralPath $OutputDirectory -Filter "particle_step_*.json" -File |
        Where-Object { $_.LastWriteTimeUtc -ge $StartedAtUtc }
).Count
if ($ParticleStepFixtureCount -ne 5) {
    throw "Unity oracle produced $ParticleStepFixtureCount particle-step fixtures instead of 5. See $LogPath"
}

$TetherRuntimeFixtureCount = @(
    Get-ChildItem -LiteralPath $OutputDirectory -Filter "tether_runtime_*.json" -File |
        Where-Object { $_.LastWriteTimeUtc -ge $StartedAtUtc }
).Count
if ($TetherRuntimeFixtureCount -ne 1) {
    throw "Unity oracle produced $TetherRuntimeFixtureCount tether-runtime fixtures instead of 1. See $LogPath"
}

$AngleRuntimeFixtureCount = @(
    Get-ChildItem -LiteralPath $OutputDirectory -Filter "angle_runtime_*.json" -File |
        Where-Object { $_.LastWriteTimeUtc -ge $StartedAtUtc }
).Count
if ($AngleRuntimeFixtureCount -ne 1) {
    throw "Unity oracle produced $AngleRuntimeFixtureCount angle-runtime fixtures instead of 1. See $LogPath"
}

$BoneConnectionFixtureCount = @(
    Get-ChildItem -LiteralPath $OutputDirectory -Filter "bone_connection_*.json" -File |
        Where-Object { $_.LastWriteTimeUtc -ge $StartedAtUtc }
).Count
if ($BoneConnectionFixtureCount -ne 8) {
    throw "Unity oracle produced $BoneConnectionFixtureCount bone-connection fixtures instead of 8. See $LogPath"
}

$BoneStaticFixtureCount = @(
    Get-ChildItem -LiteralPath $OutputDirectory -Filter "bone_static_*.json" -File |
        Where-Object { $_.LastWriteTimeUtc -ge $StartedAtUtc }
).Count
if ($BoneStaticFixtureCount -ne 3) {
    throw "Unity oracle produced $BoneStaticFixtureCount bone-static fixtures instead of 3. See $LogPath"
}

$BoneRotationLineFixtureCount = @(
    Get-ChildItem -LiteralPath $OutputDirectory -Filter "bone_rotation_line_*.json" -File |
        Where-Object { $_.LastWriteTimeUtc -ge $StartedAtUtc }
).Count
if ($BoneRotationLineFixtureCount -ne 3) {
    throw "Unity oracle produced $BoneRotationLineFixtureCount bone-rotation-line fixtures instead of 3. See $LogPath"
}

$BoneRotationTriangleFixtureCount = @(
    Get-ChildItem -LiteralPath $OutputDirectory -Filter "bone_rotation_triangle_*.json" -File |
        Where-Object { $_.LastWriteTimeUtc -ge $StartedAtUtc }
).Count
if ($BoneRotationTriangleFixtureCount -ne 3) {
    throw "Unity oracle produced $BoneRotationTriangleFixtureCount bone-rotation-triangle fixtures instead of 3. See $LogPath"
}

Write-Host "MC2 Tier A fixtures written to $OutputDirectory ($FixtureCount baseline, $ProxyFixtureCount proxy, $DistanceFixtureCount distance static, $DistanceRuntimeFixtureCount distance runtime, $BendingFixtureCount bending static, $BendingRuntimeFixtureCount bending runtime, $RuntimeParameterFixtureCount runtime parameters, $FrameResetFixtureCount frame/reset, $CenterFixtureCount center static, $CenterStepFixtureCount center step, $CenterFrameShiftFixtureCount center frame shift, $ParticleStepFixtureCount particle step, $TetherRuntimeFixtureCount tether runtime, $AngleRuntimeFixtureCount angle runtime, $BoneConnectionFixtureCount bone connection, $BoneStaticFixtureCount bone static, $BoneRotationLineFixtureCount bone rotation line, $BoneRotationTriangleFixtureCount bone rotation triangle)"
