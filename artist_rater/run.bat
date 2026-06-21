@echo off
cd /d "%~dp0"
python -c "import flask, requests, PIL, browser_cookie3, playwright" 2>nul
if errorlevel 1 python -m pip install -r requirements.txt
echo.
echo Danbooru Artist Rater
echo Open http://127.0.0.1:5001
echo.
python app.py
