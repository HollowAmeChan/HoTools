param(
    [string]$BlenderPath = "D:\Blender\blender-5.1.0-windows-x64\blender.exe"
)

$ErrorActionPreference = "Stop"
$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$ScriptPath = Join-Path $RepoRoot "OmniNode\NodeTree\Function\physicsWorld\test\test_blender_mc2_v1_soak.py"

if (-not (Test-Path -LiteralPath $BlenderPath)) {
    throw "Blender 5.1 executable not found: $BlenderPath"
}
if (-not (Test-Path -LiteralPath $ScriptPath)) {
    throw "MC2 V1-R soak script not found: $ScriptPath"
}

$StdoutPath = Join-Path $env:TEMP "hotools_mc2_v1_soak.stdout.log"
$StderrPath = Join-Path $env:TEMP "hotools_mc2_v1_soak.stderr.log"
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
    $StdoutTail = @(Get-Content -LiteralPath $StdoutPath -Tail 100 -ErrorAction SilentlyContinue)
    $StderrTail = @(Get-Content -LiteralPath $StderrPath -Tail 100 -ErrorAction SilentlyContinue)
    throw "MC2 V1-R soak failed`n$($StdoutTail -join [Environment]::NewLine)`n$($StderrTail -join [Environment]::NewLine)"
}

$Result = Get-Content -LiteralPath $StdoutPath | Select-String -Pattern "MC2 V1-R soak: PASS" | Select-Object -Last 1
if ($null -eq $Result) {
    throw "MC2 V1-R soak did not publish its result line. See $StdoutPath"
}
Write-Host $Result.Line
