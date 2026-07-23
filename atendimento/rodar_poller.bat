@echo off
cd /d "%~dp0.."
".venv\Scripts\pythonw.exe" -m atendimento.poller --uma-vez >> atendimento\poller.log 2>&1
