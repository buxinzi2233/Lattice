[CmdletBinding()]
param(
    [string]$Python = $env:LATTICE_PYTHON,
    [switch]$Repair,
    [switch]$StartMenuShortcut
)

$ErrorActionPreference = "Stop"
$ProjectDir = (Resolve-Path $PSScriptRoot).Path
$VenvDir = Join-Path $ProjectDir ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$UvVersion = if ($env:LATTICE_UV_VERSION) { $env:LATTICE_UV_VERSION } else { "0.5.31" }
$UvSha256 = if ($env:LATTICE_UV_SHA256) { $env:LATTICE_UV_SHA256 } else { "1ad54dace424c259b603ecd36262cb235af2bc8d6f280e24063d57919545f593" }
$LocalBin = Join-Path $ProjectDir ".local"
$UvExe = Join-Path $LocalBin "uv.exe"

function Invoke-Checked {
    param(
        [string]$Command,
        [string[]]$Arguments
    )
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "命令执行失败：$Command $($Arguments -join ' ')"
    }
}

function Install-Uv {
    New-Item -ItemType Directory -Force -Path $LocalBin | Out-Null
    $Arch = if ([Environment]::Is64BitOperatingSystem) { "x86_64-pc-windows-msvc" } else { throw "Lattice 仅支持 64 位 Windows" }
    $Url = "https://github.com/astral-sh/uv/releases/download/$UvVersion/uv-$Arch.zip"
    $Zip = Join-Path $env:TEMP "lattice-uv.zip"
    Invoke-WebRequest -Uri $Url -OutFile $Zip -UseBasicParsing
    $Actual = (Get-FileHash -Algorithm SHA256 -Path $Zip).Hash.ToLowerInvariant()
    if ($Actual -ne $UvSha256.ToLowerInvariant()) { throw "uv SHA256 校验失败：$Actual" }
    $Extract = Join-Path $env:TEMP "lattice-uv"
    if (Test-Path $Extract) { Remove-Item -Recurse -Force $Extract }
    Expand-Archive -Path $Zip -DestinationPath $Extract -Force
    $Found = Get-ChildItem -Path $Extract -Recurse -Filter uv.exe | Select-Object -First 1
    if (-not $Found) { throw "uv.exe 解压失败" }
    Copy-Item $Found.FullName $UvExe -Force
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue) -and -not (Test-Path $UvExe)) {
    Install-Uv
}
$UvCommand = if (Get-Command uv -ErrorAction SilentlyContinue) { "uv" } else { $UvExe }

if (-not $Python) {
    $Candidate = Get-Command python3.12 -ErrorAction SilentlyContinue
    if ($Candidate) {
        $Python = $Candidate.Source
        $PythonArgs = @()
    } else {
        Invoke-Checked $UvCommand @("python", "install", "3.12")
        $Python = (& $UvCommand python find 3.12).Trim()
        $PythonArgs = @()
    }
} else {
    $PythonArgs = @()
}

if ($Repair -and (Test-Path $VenvDir)) {
    Remove-Item -Recurse -Force $VenvDir
}

if (-not (Test-Path $VenvPython)) {
    Invoke-Checked $UvCommand @("venv", $VenvDir, "--python", $Python)
}

if (Test-Path (Join-Path $ProjectDir "uv.lock")) {
    Invoke-Checked $UvCommand @("sync", "--frozen", "--project", $ProjectDir, "--extra", "dev")
} else {
    Invoke-Checked $UvCommand @("pip", "install", "--python", $VenvPython, "-e", "${ProjectDir}[dev]")
}

$GuiCommand = Join-Path $VenvDir "Scripts\tooldeck-gui.exe"
$CliCommand = Join-Path $VenvDir "Scripts\tooldeck.exe"
Write-Host "Lattice 已安装。"
Write-Host "图形界面：$GuiCommand"
Write-Host "命令行：  $CliCommand"

if ($StartMenuShortcut) {
    $ShortcutDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
    $ShortcutPath = Join-Path $ShortcutDir "Lattice.lnk"
    $Shell = New-Object -ComObject WScript.Shell
    $Shortcut = $Shell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = $GuiCommand
    $Shortcut.WorkingDirectory = $ProjectDir
    $Shortcut.Description = "Lattice 晶格中枢"
    $Shortcut.Save()
    Write-Host "开始菜单快捷方式：$ShortcutPath"
}
