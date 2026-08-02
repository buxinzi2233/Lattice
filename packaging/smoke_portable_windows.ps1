[CmdletBinding()]
param(
    [string]$SearchRoot = "dist\Lattice-portable",
    [int]$WaitSeconds = 5
)

$ErrorActionPreference = "Stop"
$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Root = Join-Path $ProjectDir $SearchRoot
$Executable = Get-ChildItem -Path $Root -Recurse -Filter "Lattice.exe" | Select-Object -First 1
if (-not $Executable) { throw "Portable Lattice.exe was not found under $Root" }

$env:QT_QPA_PLATFORM = "offscreen"
$env:QT_QUICK_BACKEND = "software"
$Process = Start-Process -FilePath $Executable.FullName -PassThru
try {
    Start-Sleep -Seconds $WaitSeconds
    $Process.Refresh()
    if ($Process.HasExited) {
        throw "Portable Lattice exited during startup with code $($Process.ExitCode)"
    }
    Write-Host "Portable startup verified: $($Executable.FullName)"
}
finally {
    if (-not $Process.HasExited) {
        Stop-Process -Id $Process.Id -Force
    }
}
