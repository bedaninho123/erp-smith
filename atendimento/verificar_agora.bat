@echo off
REM Verifica a caixa de entrada agora mesmo, sem esperar a Tarefa Agendada
REM rodar sozinha (ela roda a cada 2 minutos). Use este arquivo sempre que
REM quiser testar algo na hora. Diferente da Tarefa Agendada, aqui a
REM janela fica visivel de proposito, pra voce ver o resultado na tela.

cd /d "%~dp0.."
".venv\Scripts\python.exe" -m atendimento.poller --uma-vez

echo.
pause
