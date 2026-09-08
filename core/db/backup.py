"""Backup do banco (Core + Domínio) e da pasta de documentos recebidos,
com rotação. Pensado pra rodar diariamente via Tarefa Agendada do
Windows (ver instalar_tarefa_backup.ps1/.bat) -- também roda manualmente
a qualquer momento.

Protege contra exclusão/corrupção acidental do arquivo em uso. NÃO É
backup externo: por padrão grava numa subpasta do próprio projeto, no
mesmo disco -- não protege contra falha física do disco. Pra proteção
real contra desastre, aponte BACKUP_DIR (.env) pra um local fora desta
máquina (pasta sincronizada com nuvem, unidade de rede, HD externo).

Usa a API de backup do próprio SQLite (Connection.backup()), não uma
cópia crua do arquivo .db -- em modo WAL (core/conexao.py), parte do
dado confirmado pode estar só no arquivo -wal, então copiar só o .db
perderia commit recente. A API do SQLite faz uma cópia consistente
mesmo com o banco em uso por outro processo (painel, poller, webhook).

Uso: `.venv\\Scripts\\python.exe -m core.db.backup`
"""
import os
import shutil
import sqlite3
import traceback
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
# Sobrescrevíveis por ERP_CORE_DB/ERP_DOMAIN_DB/ERP_DOCUMENTOS_DIR --
# mesmo padrão (e mesmo motivo) de core/conexao.py e
# core/motor_documentos.py. Sem isto, este script só sabia backupear o
# banco local -- na hospedagem (Railway), o banco de verdade mora em
# /data/..., e o script "funcionaria" sem erro nenhum enquanto faz
# backup de um arquivo que não existe (CORE_DB.exists() vira False e o
# passo simplesmente não roda -- falha silenciosa, exatamente o que este
# módulo existe pra evitar).
CORE_DB = Path(os.environ.get("ERP_CORE_DB") or (BASE_DIR / "core" / "db" / "erp_smith.db"))
DOMAIN_DB = Path(os.environ.get("ERP_DOMAIN_DB") or (BASE_DIR / "domain" / "clube_tiro" / "db" / "dominio_clube_tiro.db"))
DOCUMENTOS_DIR = Path(os.environ.get("ERP_DOCUMENTOS_DIR") or (BASE_DIR / "atendimento" / "documentos_recebidos"))

# Caminho explícito, não load_dotenv() sem argumento: sem isto o módulo
# lia só o ambiente do processo, e BACKUP_DIR no .env -- que o docstring
# acima, o .env.example e o CLAUDE.md mandam usar -- não tinha efeito
# nenhum (o backup seguia gravando na pasta do projeto, calado). O
# argumento também protege de a Tarefa Agendada rodar com outro
# diretório de trabalho, quando load_dotenv() não acharia o arquivo.
load_dotenv(BASE_DIR / ".env")

LOG_PATH = Path(__file__).resolve().parent / "backup.log"

BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", str(BASE_DIR / "backups")))
# 14 backups diários = duas semanas de histórico -- o bastante pra
# perceber um problema (dado corrompido, exclusão errada) antes que o
# backup bom saia da janela de retenção.
MANTER_ULTIMOS = int(os.environ.get("BACKUP_MANTER_ULTIMOS", "14"))


def _registrar(mensagem: str) -> None:
    """Grava no log além de imprimir. A Tarefa Agendada roda com
    pythonw.exe, que não tem console -- print() ali é descartado em
    silêncio, então o arquivo de log é a única forma de saber, depois,
    se o backup das 3h funcionou ou falhou. Horário em hora local, não
    UTC (é pra você conferir "rodou essa noite?", não pra máquina ler).
    """
    print(mensagem)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  {mensagem}\n")
    except OSError:
        # Não deixa uma falha ao escrever o log impedir o backup em si --
        # o backup é o que importa, o log é o relato dele.
        pass


def _validar_destino() -> None:
    """Exige que a pasta-mãe do BACKUP_DIR já exista.

    Existe porque o BACKUP_DIR de verdade aponta pra fora desta máquina
    (pasta do Google Drive, HD externo, unidade de rede) -- e esse tipo
    de destino às vezes não está lá na hora do backup: Drive não montado,
    pen drive desconectado, pasta renomeada. Sem esta checagem,
    mkdir(parents=True) criaria a árvore inteira num lugar errado e o
    backup terminaria com "sucesso" sem proteger nada -- exatamente a
    falha silenciosa que este backup existe pra evitar.
    """
    if not BACKUP_DIR.parent.exists():
        raise FileNotFoundError(
            f"O destino do backup não está acessível: {BACKUP_DIR}\n"
            f"A pasta que deveria contê-lo ({BACKUP_DIR.parent}) não existe. "
            "Se BACKUP_DIR aponta pro Google Drive, confirme que o Google "
            "Drive para desktop está rodando e sincronizado; se aponta pra "
            "um HD externo ou pen drive, confirme que está conectado."
        )


def _copiar_banco(origem: Path, destino: Path) -> None:
    origem_con = sqlite3.connect(str(origem))
    destino_con = sqlite3.connect(str(destino))
    try:
        # busy_timeout aqui também (mesmo motivo de core/conexao.py):
        # backup roda com o banco em uso por outro processo (o próprio
        # painel), e sem isto uma escrita em andamento no instante exato
        # da cópia vira "database is locked" em vez de só esperar.
        origem_con.execute("PRAGMA busy_timeout = 5000")
        origem_con.backup(destino_con)
    finally:
        origem_con.close()
        destino_con.close()


def _rotacionar() -> None:
    pastas = sorted(p for p in BACKUP_DIR.iterdir() if p.is_dir())
    for antiga in pastas[:-MANTER_ULTIMOS] if len(pastas) > MANTER_ULTIMOS else []:
        shutil.rmtree(antiga, ignore_errors=True)


def main(incluir_documentos: bool = True) -> None:
    """`incluir_documentos=False` existe pro backup automático dentro do
    Railway (ver webapp/servir.py): ali BACKUP_DIR aponta pra uma
    subpasta do MESMO volume onde o banco já mora (não tem HD externo
    nem Google Drive lá) -- duplicar documentos_recebidos/ e
    marketplace_fotos/ inteiros a cada rodada, com retenção de vários
    dias, encheria o volume rápido. O `.db` sozinho é pequeno; documento
    de cliente pode não ser. Backup local (Tarefa Agendada do Windows)
    continua incluindo tudo, como sempre -- lá o destino é justamente
    pensado pra ser grande e externo."""
    _validar_destino()

    agora = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    destino = BACKUP_DIR / agora
    destino.mkdir(parents=True, exist_ok=True)

    if CORE_DB.exists():
        _copiar_banco(CORE_DB, destino / "erp_smith.db")
        _registrar("  + core/db/erp_smith.db")
    if DOMAIN_DB.exists():
        _copiar_banco(DOMAIN_DB, destino / "dominio_clube_tiro.db")
        _registrar("  + domain/clube_tiro/db/dominio_clube_tiro.db")
    if incluir_documentos and DOCUMENTOS_DIR.exists():
        shutil.copytree(DOCUMENTOS_DIR, destino / "documentos_recebidos")
        _registrar("  + atendimento/documentos_recebidos/")

    _rotacionar()
    _registrar(f"OK -- backup salvo em {destino}")


if __name__ == "__main__":
    # Qualquer falha vira uma linha no log E código de saída != 0 (que a
    # Tarefa Agendada guarda em LastTaskResult, visível por
    # `Get-ScheduledTaskInfo`). Antes, uma falha às 3h da manhã não
    # deixava rastro em lugar nenhum.
    try:
        main()
    except Exception as e:
        _registrar(f"FALHOU -- {type(e).__name__}: {e}")
        _registrar(traceback.format_exc().rstrip())
        raise
