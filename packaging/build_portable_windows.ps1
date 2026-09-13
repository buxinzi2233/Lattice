[CmdletBinding()]
param(
    [string]$OutputDir = "dist\Lattice-portable",
    [switch]$Repair
)

$ErrorActionPreference = "Stop"
$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$OutputPath = Join-Path $ProjectDir $OutputDir

& (Join-Path $ProjectDir "install.ps1") -Repair:$Repair
$Python = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$UvCommand = if (Get-Command uv -ErrorAction SilentlyContinue) {
    "uv"
} else {
    Join-Path $ProjectDir ".local\uv.exe"
}

& $UvCommand sync --frozen --project $ProjectDir --extra dev --extra build
if ($LASTEXITCODE -ne 0) { throw "Windows build dependency sync failed" }

if (Test-Path $OutputPath) { Remove-Item -Recurse -Force $OutputPath }
New-Item -ItemType Directory -Force -Path $OutputPath | Out-Null

& $Python -m nuitka --standalone --assume-yes-for-downloads --enable-plugin=pyside6 --include-qt-plugins=qml --include-distribution-metadata=tooldeck --include-package=tooldeck --include-package-data=tooldeck.gui --windows-icon-from-ico="$ProjectDir\src\tooldeck\gui\assets\lattice.ico" --output-filename=Lattice.exe --output-dir="$OutputPath" "$ProjectDir\packaging\lattice_windows_entry.py"
if ($LASTEXITCODE -ne 0) { throw "Nuitka portable build failed" }

$StandaloneDir = Get-ChildItem -Path $OutputPath -Directory -Filter "*.dist" | Select-Object -First 1
if (-not $StandaloneDir) { throw "Nuitka standalone output directory was not found" }
$Version = & $Python -c "import importlib.metadata; print(importlib.metadata.version('tooldeck'))"
if ($LASTEXITCODE -ne 0) { throw "Cannot read installed project version" }
$ArchiveName = "Lattice-$Version-windows-portable.zip"
$Archive = Join-Path $ProjectDir "dist\$ArchiveName"
Compress-Archive -Path (Join-Path $StandaloneDir.FullName "*") -DestinationPath $Archive -Force
$Hash = (Get-FileHash -Algorithm SHA256 $Archive).Hash.ToLowerInvariant()
"$Hash *$ArchiveName" | Set-Content -Encoding ascii (Join-Path $ProjectDir "dist\SHA256SUMS-windows.txt")
Write-Host "SHA256 $Hash"
