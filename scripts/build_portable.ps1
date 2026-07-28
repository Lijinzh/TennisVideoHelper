param(
    [string]$FfmpegDirectory = "",
    [ValidateSet("Full", "Compact")]
    [string]$Edition = "Full",
    [switch]$SkipDependencySync
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$RuntimeDirectory = Join-Path $ProjectRoot "runtime"

if (-not $FfmpegDirectory) {
    $FfmpegCommand = Get-Command ffmpeg.exe -ErrorAction Stop
    $FfmpegDirectory = Split-Path -Parent $FfmpegCommand.Source
}
$FfmpegDirectory = (Resolve-Path -LiteralPath $FfmpegDirectory).Path

$RequiredTools = @("ffmpeg.exe", "ffprobe.exe")
foreach ($Tool in $RequiredTools) {
    $Source = Join-Path $FfmpegDirectory $Tool
    if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) {
        throw "FFmpeg 目录缺少 $Tool：$FfmpegDirectory"
    }
}

New-Item -ItemType Directory -Force -Path $RuntimeDirectory | Out-Null
foreach ($Tool in $RequiredTools) {
    Copy-Item -LiteralPath (Join-Path $FfmpegDirectory $Tool) -Destination $RuntimeDirectory -Force
}

Push-Location $ProjectRoot
try {
    if (-not $SkipDependencySync) {
        uv sync --extra dev --extra gpu-max --extra package
        if ($LASTEXITCODE -ne 0) { throw "uv sync 失败，退出代码 $LASTEXITCODE" }
    }

    $env:TVH_PACKAGE_EDITION = $Edition.ToLowerInvariant()
    uv run pyinstaller --noconfirm --clean packaging\tennis_video_helper.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller 失败，退出代码 $LASTEXITCODE" }

    $DirectoryName = if ($Edition -eq "Compact") { "TennisVideoHelper-Compact" } else { "TennisVideoHelper" }
    $Output = Join-Path $ProjectRoot "dist\$DirectoryName"
    $Bytes = (Get-ChildItem -LiteralPath $Output -Recurse -File | Measure-Object Length -Sum).Sum
    Write-Host ("便携版已生成：{0} ({1:N1} MiB)" -f $Output, ($Bytes / 1MB))
}
finally {
    Remove-Item Env:TVH_PACKAGE_EDITION -ErrorAction SilentlyContinue
    Pop-Location
}
