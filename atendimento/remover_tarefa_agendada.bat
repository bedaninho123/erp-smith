@echo off
REM Remove a Tarefa Agendada do verificador de e-mail. Use se quiser
REM parar o recebimento automatico (o envio/testes manuais continuam
REM funcionando normalmente -- isso so desliga a verificacao periodica).

schtasks /delete /tn "ERPSmithPoller" /f

if %errorlevel%==0 (
    echo Tarefa "ERPSmithPoller" removida.
) else (
    echo Nao encontrei a tarefa "ERPSmithPoller" -- talvez ja estivesse removida.
)
