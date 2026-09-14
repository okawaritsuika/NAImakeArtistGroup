param(
    [string]$PythonExecutable = "python",
    [string]$SeedSource = ""
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$appDir = Join-Path $root "artist_rater"
$releaseDir = Join-Path $root "release"
$workDir = Join-Path $appDir ".build"
$templatesDir = Join-Path $appDir "templates"
$staticDir = Join-Path $appDir "static"
$seedDb = Join-Path $appDir "arca_style_seed.sqlite"

New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null
Push-Location $appDir
try {
    # Use the verified release seed by default. Never silently package a local user DB.
    if ($SeedSource) {
        & $PythonExecutable export_arca_seed.py --source $SeedSource --output $seedDb
        if ($LASTEXITCODE -ne 0) { throw "Shared-style seed export failed." }
    }
    & $PythonExecutable -c "import hashlib; from pathlib import Path; from arca_image_archive import ARCHIVE_SEED_SHA256; assert hashlib.sha256(Path('arca_style_seed.sqlite').read_bytes()).hexdigest() == ARCHIVE_SEED_SHA256, 'Seed and shared image pack do not match'"
    if ($LASTEXITCODE -ne 0) { throw "Shared-style seed and image pack verification failed." }
    & $PythonExecutable -c "import tkinter; tkinter.Tcl().eval('info library')"
    if ($LASTEXITCODE -ne 0) { throw "Tcl/Tk is unavailable. Build with a Python environment that can initialize Tkinter." }
    & $PythonExecutable -m PyInstaller `
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
