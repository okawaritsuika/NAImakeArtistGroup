$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$appDir = Join-Path $root "artist_rater"
$releaseDir = Join-Path $root "release"
$workDir = Join-Path $appDir ".build"
$templatesDir = Join-Path $appDir "templates"
$staticDir = Join-Path $appDir "static"
$sourceDb = Join-Path $appDir "data\artist_rater.sqlite"
$seedDb = Join-Path $appDir "arca_style_seed.sqlite"

New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null
Push-Location $appDir
try {
    python export_arca_seed.py --source $sourceDb --output $seedDb
    if ($LASTEXITCODE -ne 0) { throw "Shared-style seed export failed." }
    python -m PyInstaller `
        --noconfirm `
        --clean `
        --onefile `
        --windowed `
        --name DanbooruArtistRater `
        --distpath $releaseDir `
        --workpath $workDir `
        --specpath $workDir `
        --add-data "$templatesDir;templates" `
        --add-data "$staticDir;static" `
        --add-data "$seedDb;." `
        --collect-all playwright `
        --hidden-import app `
        --hidden-import browser_cookie3 `
        launcher.py
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }
} finally {
    Pop-Location
}

Write-Host "Built: $(Join-Path $releaseDir 'DanbooruArtistRater.exe')"
