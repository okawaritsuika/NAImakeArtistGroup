@echo off
cd /d "%~dp0"
py -3.10 -c "import flask, requests, PIL, browser_cookie3, playwright" 2>nul
if errorlevel 1 py -3.10 -m pip install -r requirements.txt
echo.
echo Danbooru Artist Rater
echo Starting remote control
echo.
py -3.10 launcher.py
