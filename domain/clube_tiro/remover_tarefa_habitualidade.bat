@echo off
REM Remove a Tarefa Agendada da sincronizacao de habitualidade.
REM O painel continua funcionando -- so para de atualizar sozinho, e o
REM "Retrato de" da tela vai ficando cada vez mais velho.

schtasks /Delete /TN "ERPSmithHabitualidade" /F

if %errorlevel%==0 (
    echo.
    echo Tarefa removida.
) else (
    echo.
    echo Nao foi possivel remover -- talvez ela ja nao exista.
)
