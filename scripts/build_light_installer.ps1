param(
    [Parameter(Mandatory = $true)]
    [string]$FfmpegDirectory,
    [string]$InnoCompiler = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$RuntimeDirectory = Join-Path $ProjectRoot "runtime"
$BuildVenv = Join-Path $ProjectRoot ".build-venv-light"
$BuildPython = Join-Path $BuildVenv "Scripts\python.exe"

if (-not $InnoCompiler) {
    $InnoCandidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe"
    )
    $InnoCompiler = $InnoCandidates |
        Where-Object { Test-Path -LiteralPath $_ } |
        Select-Object -First 1
}

$FfmpegDirectory = (Resolve-Path -LiteralPath $FfmpegDirectory).Path
foreach ($Name in @("ffmpeg.exe", "ffprobe.exe")) {
    if (-not (Test-Path -LiteralPath (Join-Path $FfmpegDirectory $Name))) {
        throw "共享 FFmpeg 目录缺少 $Name"
    }
}

New-Item -ItemType Directory -Force -Path $RuntimeDirectory | Out-Null
Get-ChildItem -LiteralPath $RuntimeDirectory -File -ErrorAction SilentlyContinue |
    ForEach-Object { [System.IO.File]::Delete($_.FullName) }
Get-ChildItem -LiteralPath $FfmpegDirectory -File |
    Copy-Item -Destination $RuntimeDirectory -Force

Push-Location $ProjectRoot
try {
    uv venv --clear $BuildVenv --python 3.12
    if ($LASTEXITCODE -ne 0) { throw "创建轻量构建环境失败" }
    uv pip install --python $BuildPython `
        "numpy>=2.0" `
        "opencv-python>=4.11" `
        "pyside6>=6.11.1" `
        "soundfile>=0.13" `
        "typer>=0.16" `
        "onnxruntime-directml>=1.22" `
        "pyinstaller>=6.21"
    if ($LASTEXITCODE -ne 0) { throw "安装轻量构建依赖失败" }
    uv pip install --python $BuildPython --no-deps -e .
    if ($LASTEXITCODE -ne 0) { throw "安装项目失败" }

    & $BuildPython -m PyInstaller --noconfirm --clean packaging\tennis_video_helper_light.spec
    if ($LASTEXITCODE -ne 0) { throw "轻量程序构建失败" }

    $Portable = Join-Path $ProjectRoot "dist\TennisVideoHelper-Light"
    $BundledRuntime = Join-Path $Portable "_internal\runtime"
    Get-ChildItem -LiteralPath $BundledRuntime -File |
        Where-Object { $_.Name -notin @("ffmpeg.exe", "ffprobe.exe") } |
        ForEach-Object { [System.IO.File]::Delete($_.FullName) }

    if (-not (Test-Path -LiteralPath $InnoCompiler)) {
        throw "找不到 Inno Setup 编译器：$InnoCompiler"
    }
    & $InnoCompiler packaging\TennisVideoHelper.iss
    if ($LASTEXITCODE -ne 0) { throw "安装包生成失败" }

    $Installer = Join-Path $ProjectRoot "dist\installer\TennisVideoHelper-Setup.exe"
    $InstalledBytes = (Get-ChildItem -LiteralPath $Portable -File -Recurse | Measure-Object Length -Sum).Sum
    $InstallerBytes = (Get-Item -LiteralPath $Installer).Length
    [pscustomobject]@{
        Installer = $Installer
        InstallerMiB = [math]::Round($InstallerBytes / 1MB, 1)
        InstalledMiB = [math]::Round($InstalledBytes / 1MB, 1)
    } | Format-List
}
finally {
    Pop-Location
}
