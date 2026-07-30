[CmdletBinding()]
param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$archiveDirectory = Join-Path $PSScriptRoot "extern\archives"
$archivePath = Join-Path $archiveDirectory "boost_1_86_0.tar.gz"
$partialPath = "$archivePath.partial"
$downloadUrl = "https://archives.boost.io/release/1.86.0/source/boost_1_86_0.tar.gz"
$expectedMd5 = "AC857D73BB754B718A039830B07B9624"

function Test-ArchiveHash {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return $false
    }
    return (Get-FileHash -LiteralPath $Path -Algorithm MD5).Hash -eq $expectedMd5
}

New-Item -ItemType Directory -Path $archiveDirectory -Force | Out-Null

if ((Test-ArchiveHash -Path $archivePath) -and -not $Force) {
    Write-Host "[OK] Boost 1.86.0 archive is already present and verified."
    exit 0
}

if ((Test-Path -LiteralPath $archivePath) -and -not $Force) {
    throw "Existing Boost archive failed MD5 verification. Re-run with -Force to replace it."
}

Remove-Item -LiteralPath $partialPath -Force -ErrorAction SilentlyContinue
Write-Host "Downloading Boost 1.86.0..."
Invoke-WebRequest -Uri $downloadUrl -OutFile $partialPath

if (-not (Test-ArchiveHash -Path $partialPath)) {
    Remove-Item -LiteralPath $partialPath -Force
    throw "Downloaded Boost archive failed MD5 verification."
}

Move-Item -LiteralPath $partialPath -Destination $archivePath -Force
Write-Host "[OK] Saved verified archive to $archivePath"
Write-Host "CMake stores pinned libigl/CGAL/Eigen sources in _native\.fetch-cache."
