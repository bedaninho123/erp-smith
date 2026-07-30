@echo off
REM Remove a Tarefa Agendada de backup diario. O script core/db/backup.py
REM continua podendo ser rodado manualmente -- isso so desliga a
REM execucao automatica.

schtasks /delete /tn "ERPSmithBackup" /f

if %errorlevel%==0 (
    echo Tarefa "ERPSmithBackup" removida.
) else (
    echo Nao encontrei a tarefa "ERPSmithBackup" -- talvez ja estivesse removida.
)
