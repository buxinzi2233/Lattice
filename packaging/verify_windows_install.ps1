[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Installer = Join-Path $ProjectDir "install.ps1"
$ExpectedTarget = Join-Path $ProjectDir ".venv\Scripts\tooldeck-gui.exe"
$ShortcutPath = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Lattice.lnk"

& powershell -NoProfile -ExecutionPolicy Bypass -File $Installer -StartMenuShortcut
if ($LASTEXITCODE -ne 0) { throw "Windows source installer failed" }

try {
    if (-not (Test-Path -LiteralPath $ShortcutPath)) {
        throw "Lattice start menu shortcut was not created"
    }
    $Shell = New-Object -ComObject WScript.Shell
    $Shortcut = $Shell.CreateShortcut($ShortcutPath)
    if ($Shortcut.TargetPath -ne $ExpectedTarget) {
        throw "Unexpected shortcut target: $($Shortcut.TargetPath)"
    }
    if ($Shortcut.WorkingDirectory -ne $ProjectDir) {
        throw "Unexpected shortcut working directory: $($Shortcut.WorkingDirectory)"
    }
    Write-Host "Windows installer shortcut verified: $ShortcutPath"
}
finally {
    Remove-Item -LiteralPath $ShortcutPath -Force -ErrorAction SilentlyContinue
}
