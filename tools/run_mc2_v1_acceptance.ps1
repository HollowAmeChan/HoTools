param(
    [string]$BlenderPath = "D:\Blender\blender-5.1.0-windows-x64\blender.exe",
    [string]$ManifestPath = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
if (-not $ManifestPath) {
    $ManifestPath = Join-Path $RepoRoot "OmniNode\NodeTree\Function\physicsWorld\mc2\test\acceptance_assets_v1.json"
}
$ManifestPath = [System.IO.Path]::GetFullPath($ManifestPath)

if (-not (Test-Path -LiteralPath $BlenderPath)) {
    throw "Blender 5.1 executable not found: $BlenderPath"
}
if (-not (Test-Path -LiteralPath $ManifestPath)) {
    throw "MC2 V1-R acceptance manifest not found: $ManifestPath"
}

$Manifest = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($Manifest.schema -ne "mc2_v1_acceptance_assets_v0") {
    throw "Unsupported MC2 acceptance manifest schema: $($Manifest.schema)"
}
if ($Manifest.acceptance_profile -ne "V1-R") {
    throw "Unexpected MC2 acceptance profile: $($Manifest.acceptance_profile)"
}
if ($Manifest.environment.python -ne "3.13" -or $Manifest.environment.blender -ne "5.1") {
    throw "MC2 V1-R acceptance requires Python 3.13 and Blender 5.1"
}

$SetupTypes = @($Manifest.assets | ForEach-Object { $_.setup_types } | Sort-Object -Unique)
$ExpectedSetupTypes = @("bone_cloth", "bone_spring", "mesh_cloth")
if ((Compare-Object $SetupTypes $ExpectedSetupTypes).Count -ne 0) {
    throw "Acceptance manifest must cover exactly mesh_cloth, bone_cloth, and bone_spring"
}

$ScriptPaths = @(
    $Manifest.assets |
        ForEach-Object { [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $_.script)) } |
        Sort-Object -Unique
)
foreach ($ScriptPath in $ScriptPaths) {
    if (-not $ScriptPath.StartsWith($RepoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Acceptance script escapes repository root: $ScriptPath"
    }
    if (-not (Test-Path -LiteralPath $ScriptPath)) {
        throw "Acceptance script not found: $ScriptPath"
    }

    $ScriptName = [System.IO.Path]::GetFileNameWithoutExtension($ScriptPath)
    $StdoutPath = Join-Path $env:TEMP "hotools_$ScriptName.stdout.log"
    $StderrPath = Join-Path $env:TEMP "hotools_$ScriptName.stderr.log"
    $Arguments = @(
        "--background",
        "--factory-startup",
        "--python", "`"$ScriptPath`""
    )
    $Process = Start-Process `
        -FilePath $BlenderPath `
        -ArgumentList $Arguments `
        -WindowStyle Hidden `
        -RedirectStandardOutput $StdoutPath `
        -RedirectStandardError $StderrPath `
        -Wait `
        -PassThru
    if ($Process.ExitCode -ne 0) {
        $StdoutTail = @(Get-Content -LiteralPath $StdoutPath -Tail 60 -ErrorAction SilentlyContinue)
        $StderrTail = @(Get-Content -LiteralPath $StderrPath -Tail 60 -ErrorAction SilentlyContinue)
        throw "MC2 V1-R asset failed: $ScriptName`n$($StdoutTail -join [Environment]::NewLine)`n$($StderrTail -join [Environment]::NewLine)"
    }
    Write-Host "PASS $ScriptName"
}

Write-Host "MC2 V1-R representative assets passed: $($Manifest.assets.Count) assets, $($ScriptPaths.Count) Blender scripts"
