# Cria (ou atualiza, se ja existir) a Tarefa Agendada do Windows que roda
# o verificador de e-mail (atendimento/poller.py) a cada 2 minutos, mesmo
# sem terminal aberto e sem flashar janela nenhuma na tela.
#
# Diferente da versao anterior (que chamava um .bat, executado via
# cmd.exe): cmd.exe sempre abre uma janela de console por uma fracao de
# segundo ao rodar um .bat pela Tarefa Agendada, mesmo que o programa de
# dentro (pythonw.exe) nao tenha janela nenhuma -- era essa janela do
# cmd.exe que estava flashando, nao o Python. Aqui a Acao chama
# pythonw.exe diretamente, sem nenhum .bat/cmd.exe no meio.
#
# (Nao usa LogonType S4U/"rodar mesmo sem estar logado" porque isso exige
# PowerShell como Administrador so pra registrar a tarefa -- fica no modo
# padrao, "so quando o usuario estiver logado", igual antes.)

$ErrorActionPreference = "Stop"

$raiz = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonw = Join-Path $raiz ".venv\Scripts\pythonw.exe"

if (-not (Test-Path $pythonw)) {
    Write-Error "Nao encontrei $pythonw -- confirme que o .venv foi criado (ver requirements.txt)."
}

$acao = New-ScheduledTaskAction -Execute $pythonw -Argument "-m atendimento.poller --uma-vez" -WorkingDirectory $raiz

$gatilho = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 2) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$config = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 72)

Register-ScheduledTask -TaskName "ERPSmithPoller" -Action $acao -Trigger $gatilho -Settings $config -Force | Out-Null

Write-Host "Tarefa `"ERPSmithPoller`" criada/atualizada com sucesso -- roda a cada 2 minutos, sem abrir janela."
