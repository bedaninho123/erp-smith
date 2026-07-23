@echo off
REM Cria (ou atualiza, se ja existir) a Tarefa Agendada do Windows que
REM roda o verificador de e-mail (atendimento/poller.py) a cada 2
REM minutos, mesmo sem terminal aberto. Rode este arquivo de novo se
REM mudar de computador ou se a tarefa for removida por engano.
REM
REM A tarefa em si mora no Windows (nao tem como um arquivo de projeto
REM substituir isso -- e o proprio sistema operacional que guarda
REM tarefas agendadas), mas o COMANDO que cria ela fica aqui, versionado.

schtasks /create /tn "ERPSmithPoller" /tr "\"%~dp0rodar_poller.bat\"" /sc minute /mo 2 /f

if %errorlevel%==0 (
    echo.
    echo Tarefa "ERPSmithPoller" criada/atualizada com sucesso -- roda a cada 2 minutos.
) else (
    echo.
    echo Falha ao criar a tarefa. Confira se voce tem permissao para criar tarefas agendadas neste Windows.
)
