# Cria (ou atualiza, se ja existir) a Tarefa Agendada do Windows que
# sincroniza filiados e habitualidade a partir do Shooting House.
#
# Mesmo padrao de core/db/instalar_tarefa_backup.ps1: a Acao chama
# pythonw.exe diretamente, sem .bat/cmd.exe no meio (evita a janela do
# cmd.exe flashando na tela a cada execucao).
#
# POR QUE 4x AO DIA, E NAO DE MINUTO EM MINUTO:
# habitualidade se consulta um CPF por vez, e um clube real tem mais de
# 900 filiados ativos. Cada rodada atende os 150 que estao ha mais tempo
# sem sincronizar (--limite), entao quatro rodadas cobrem ~600 pessoas
# por dia e o rodizio passa por todo mundo em poucos dias, sem despejar
# o clube inteiro na API do fornecedor de uma vez. Ainda nao se sabe se
# eles impoem limite de chamadas -- ate saber, este ritmo e deliberado.
#
# O lancamento de habitualidade acontece no tablet, depois do tiro; um
# atraso de algumas horas no panorama nao muda decisao nenhuma. Quem
# precisa da resposta exata de uma pessoa consulta ao vivo.

$ErrorActionPreference = "Stop"

$raiz = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$pythonw = Join-Path $raiz ".venv\Scripts\pythonw.exe"

if (-not (Test-Path $pythonw)) {
    Write-Error "Nao encontrei $pythonw -- confirme que o .venv foi criado (ver requirements.txt)."
}

$acao = New-ScheduledTaskAction -Execute $pythonw `
    -Argument "-m domain.clube_tiro.sincronizar_habitualidade --limite 150" `
    -WorkingDirectory $raiz

$gatilhos = @(
    New-ScheduledTaskTrigger -Daily -At "07:00",
    New-ScheduledTaskTrigger -Daily -At "12:00",
    New-ScheduledTaskTrigger -Daily -At "18:00",
    New-ScheduledTaskTrigger -Daily -At "23:00"
)

# IgnoreNew: se uma rodada demorar mais que o intervalo, a proxima e
# descartada em vez de empilhar duas varreduras na API ao mesmo tempo.
$config = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask -TaskName "ERPSmithHabitualidade" -Action $acao `
    -Trigger $gatilhos -Settings $config -Force | Out-Null

Write-Host "Tarefa `"ERPSmithHabitualidade`" criada/atualizada -- roda as 7h, 12h, 18h e 23h."
Write-Host ""
Write-Host "Enquanto SHOOTING_HOUSE_ATIVO estiver vazio, ela sincroniza dado SIMULADO."
