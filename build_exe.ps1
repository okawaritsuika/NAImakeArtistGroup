$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$appDir = Join-Path $root "artist_rater"
$releaseDir = Join-Path $root "release"
$workDir = Join-Path $appDir ".build"
$templatesDir = Join-Path $appDir "templates"
$staticDir = Join-Path $appDir "static"

New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null
Push-Location $appDir
try {
    python -m PyInstaller `
        --noconfirm `
        --clean `
        --onefile `
        --name DanbooruArtistRater `
        --distpath $releaseDir `
        --workpath $workDir `
        --specpath $workDir `
        --add-data "$templatesDir;templates" `
        --add-data "$staticDir;static" `
        --collect-all playwright `
        --hidden-import browser_cookie3 `
        app.py
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }
} finally {
    Pop-Location
}

Write-Host "Built: $(Join-Path $releaseDir 'DanbooruArtistRater.exe')"
