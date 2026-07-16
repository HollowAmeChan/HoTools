param(
    [string]$BlenderPath = "D:\Blender\blender-5.1.0-windows-x64\blender.exe"
)

$ErrorActionPreference = "Stop"
$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$ScriptPath = Join-Path $RepoRoot "OmniNode\NodeTree\Function\physicsWorld\test\benchmark_blender_mc2_replacement.py"
if (-not (Test-Path -LiteralPath $BlenderPath)) {
    throw "Blender 5.1 executable not found: $BlenderPath"
}
if (-not (Test-Path -LiteralPath $ScriptPath)) {
    throw "MC2 replacement benchmark not found: $ScriptPath"
}

& $BlenderPath --background --factory-startup --python $ScriptPath
if ($LASTEXITCODE -ne 0) {
    throw "MC2 replacement benchmark failed with exit code $LASTEXITCODE"
}
