@echo off
REM Cria (ou atualiza, se ja existir) a Tarefa Agendada do Windows que
REM roda o verificador de e-mail (atendimento/poller.py) a cada 2
REM minutos, mesmo sem terminal aberto e sem flashar janela nenhuma.
REM Rode este arquivo de novo se mudar de computador ou se a tarefa for
REM removida por engano.
REM
REM A tarefa em si mora no Windows (nao tem como um arquivo de projeto
REM substituir isso -- e o proprio sistema operacional que guarda
REM tarefas agendadas), mas o COMANDO que cria ela fica aqui, versionado
REM (agora em PowerShell, ver instalar_tarefa_agendada.ps1 -- necessario
REM pra eliminar de vez a janela que flashava a cada execucao).

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar_tarefa_agendada.ps1"

if %errorlevel%==0 (
    echo.
    echo Pronto.
) else (
    echo.
    echo Falha ao criar a tarefa. Confira se voce tem permissao para criar tarefas agendadas neste Windows.
)
