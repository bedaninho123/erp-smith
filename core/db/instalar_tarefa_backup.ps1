# Cria (ou atualiza, se ja existir) a Tarefa Agendada do Windows que roda
# o backup diario do banco e dos documentos (core/db/backup.py), todo dia
# as 3h da manha, mesmo sem terminal aberto e sem flashar janela.
#
# Mesmo padrao de atendimento/instalar_tarefa_agendada.ps1: a Acao chama
# pythonw.exe diretamente, sem .bat/cmd.exe no meio (evita a janela do
# cmd.exe flashando na tela a cada execucao).

$ErrorActionPreference = "Stop"

$raiz = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$pythonw = Join-Path $raiz ".venv\Scripts\pythonw.exe"

if (-not (Test-Path $pythonw)) {
    Write-Error "Nao encontrei $pythonw -- confirme que o .venv foi criado (ver requirements.txt)."
}

$acao = New-ScheduledTaskAction -Execute $pythonw -Argument "-m core.db.backup" -WorkingDirectory $raiz

$gatilho = New-ScheduledTaskTrigger -Daily -At "03:00"

$config = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Register-ScheduledTask -TaskName "ERPSmithBackup" -Action $acao -Trigger $gatilho -Settings $config -Force | Out-Null

Write-Host "Tarefa `"ERPSmithBackup`" criada/atualizada com sucesso -- roda todo dia as 3h."
