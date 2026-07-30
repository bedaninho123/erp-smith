@echo off
REM Cria (ou atualiza, se ja existir) a Tarefa Agendada do Windows que
REM roda o backup diario do banco e dos documentos (core/db/backup.py).
REM Rode este arquivo de novo se mudar de computador ou se a tarefa for
REM removida por engano.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar_tarefa_backup.ps1"

if %errorlevel%==0 (
    echo.
    echo Pronto.
) else (
    echo.
    echo Falha ao criar a tarefa. Confira se voce tem permissao para criar tarefas agendadas neste Windows.
)
