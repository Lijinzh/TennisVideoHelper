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
        throw "FFmpeg directory is missing $Name"
    }
}

New-Item -ItemType Directory -Force -Path $RuntimeDirectory | Out-Null
Get-ChildItem -LiteralPath $RuntimeDirectory -File -ErrorAction SilentlyContinue |
    ForEach-Object { [System.IO.File]::Delete($_.FullName) }
foreach ($Name in @("ffmpeg.exe", "ffprobe.exe")) {
    Copy-Item -LiteralPath (Join-Path $FfmpegDirectory $Name) `
        -Destination $RuntimeDirectory -Force
}
$FfmpegDistributionDirectory = Split-Path -Parent $FfmpegDirectory
foreach ($Notice in @(
    @{ Source = "LICENSE"; Target = "FFmpeg-LICENSE.txt" },
    @{ Source = "README.txt"; Target = "FFmpeg-README.txt" }
)) {
    $NoticeSource = Join-Path $FfmpegDistributionDirectory $Notice.Source
    if (Test-Path -LiteralPath $NoticeSource) {
        Copy-Item -LiteralPath $NoticeSource `
            -Destination (Join-Path $RuntimeDirectory $Notice.Target) -Force
    }
}

Push-Location $ProjectRoot
try {
    uv venv --clear $BuildVenv --python 3.12
    if ($LASTEXITCODE -ne 0) { throw "Failed to create the light build environment" }
    uv pip install --python $BuildPython `
        "numpy>=2.0" `
        "opencv-python>=4.11" `
        "pyside6>=6.11.1" `
        "soundfile>=0.13" `
        "typer>=0.16" `
        "onnxruntime-directml>=1.22" `
        "pyinstaller>=6.21"
    if ($LASTEXITCODE -ne 0) { throw "Failed to install light build dependencies" }
    uv pip install --python $BuildPython --no-deps -e .
    if ($LASTEXITCODE -ne 0) { throw "Failed to install the project" }

    & $BuildPython -m PyInstaller --noconfirm --clean packaging\tennis_video_helper_light.spec
    if ($LASTEXITCODE -ne 0) { throw "Failed to build the light application" }

    $Portable = Join-Path $ProjectRoot "dist\TennisVideoHelper-Light"
    $BundledRuntime = Join-Path $Portable "_internal\runtime"
    Get-ChildItem -LiteralPath $BundledRuntime -File |
        Where-Object {
            $_.Name -notin @(
                "ffmpeg.exe",
                "ffprobe.exe",
                "FFmpeg-LICENSE.txt",
                "FFmpeg-README.txt"
            )
        } |
        ForEach-Object { [System.IO.File]::Delete($_.FullName) }

    $PySideDirectory = Join-Path $Portable "_internal\PySide6"
    $UnusedQtPaths = @(
        "translations",
        "plugins\platforminputcontexts",
        "Qt6Pdf.dll",
        "Qt6PdfWidgets.dll",
        "Qt6Qml.dll",
        "Qt6QmlMeta.dll",
        "Qt6QmlModels.dll",
        "Qt6QmlWorkerScript.dll",
        "Qt6Quick.dll",
        "Qt6QuickWidgets.dll",
        "Qt6VirtualKeyboard.dll",
        "QtPdf.pyd",
        "QtPdfWidgets.pyd",
        "QtQml.pyd",
        "QtQuick.pyd",
        "QtQuickWidgets.pyd"
    )
    foreach ($RelativePath in $UnusedQtPaths) {
        $Target = Join-Path $PySideDirectory $RelativePath
        if ([System.IO.Directory]::Exists($Target)) {
            [System.IO.Directory]::Delete($Target, $true)
        }
        elseif ([System.IO.File]::Exists($Target)) {
            [System.IO.File]::Delete($Target)
        }
    }

    if (-not (Test-Path -LiteralPath $InnoCompiler)) {
        throw "Inno Setup compiler was not found: $InnoCompiler"
    }
    $ProjectVersion = (& $BuildPython -c "from tennis_video_helper import __version__; print(__version__)").Trim()
    if (-not $ProjectVersion) { throw "Failed to read the project version" }
    & $InnoCompiler "/DMyAppVersion=$ProjectVersion" packaging\TennisVideoHelper.iss
    if ($LASTEXITCODE -ne 0) { throw "Failed to build the installer" }

    $Installer = Join-Path $ProjectRoot "dist\installer\TennisVideoHelper-Setup-$ProjectVersion.exe"
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
