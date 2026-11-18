@echo off
rem Launch iPhone App Manager with Python 3.12
cd /d "%~dp0"
py -3.12 main.py
if errorlevel 1 pause
