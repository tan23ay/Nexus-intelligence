@echo off
cd /d "%~dp0"
start "" http://localhost:8787
python local\serve.py 8787
