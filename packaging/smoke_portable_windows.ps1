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
$TempPrefix = Join-Path ([System.IO.Path]::GetTempPath()) ("lattice-portable-smoke-" + [guid]::NewGuid().ToString("N"))
$StdoutPath = "$TempPrefix.stdout.log"
$StderrPath = "$TempPrefix.stderr.log"
$Process = Start-Process -FilePath $Executable.FullName -PassThru -RedirectStandardOutput $StdoutPath -RedirectStandardError $StderrPath
try {
    Start-Sleep -Seconds $WaitSeconds
    $Process.Refresh()
    if ($Process.HasExited) {
        $Stdout = if (Test-Path $StdoutPath) { Get-Content -Raw -ErrorAction SilentlyContinue $StdoutPath } else { "" }
        $Stderr = if (Test-Path $StderrPath) { Get-Content -Raw -ErrorAction SilentlyContinue $StderrPath } else { "" }
        throw "Portable Lattice exited during startup with code $($Process.ExitCode). stdout: $Stdout stderr: $Stderr"
    }
    Write-Host "Portable startup verified: $($Executable.FullName)"
}
finally {
    if (-not $Process.HasExited) {
        Stop-Process -Id $Process.Id -Force
    }
    Remove-Item -Force -ErrorAction SilentlyContinue $StdoutPath, $StderrPath
}
