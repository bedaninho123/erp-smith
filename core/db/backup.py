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
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CORE_DB = BASE_DIR / "core" / "db" / "erp_smith.db"
DOMAIN_DB = BASE_DIR / "domain" / "clube_tiro" / "db" / "dominio_clube_tiro.db"
DOCUMENTOS_DIR = BASE_DIR / "atendimento" / "documentos_recebidos"

BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", str(BASE_DIR / "backups")))
# 14 backups diários = duas semanas de histórico -- o bastante pra
# perceber um problema (dado corrompido, exclusão errada) antes que o
# backup bom saia da janela de retenção.
MANTER_ULTIMOS = int(os.environ.get("BACKUP_MANTER_ULTIMOS", "14"))


def _copiar_banco(origem: Path, destino: Path) -> None:
    origem_con = sqlite3.connect(str(origem))
    destino_con = sqlite3.connect(str(destino))
    try:
        origem_con.backup(destino_con)
    finally:
        origem_con.close()
        destino_con.close()


def _rotacionar() -> None:
    pastas = sorted(p for p in BACKUP_DIR.iterdir() if p.is_dir())
    for antiga in pastas[:-MANTER_ULTIMOS] if len(pastas) > MANTER_ULTIMOS else []:
        shutil.rmtree(antiga, ignore_errors=True)


def main() -> None:
    agora = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    destino = BACKUP_DIR / agora
    destino.mkdir(parents=True, exist_ok=True)

    if CORE_DB.exists():
        _copiar_banco(CORE_DB, destino / "erp_smith.db")
        print("  + core/db/erp_smith.db")
    if DOMAIN_DB.exists():
        _copiar_banco(DOMAIN_DB, destino / "dominio_clube_tiro.db")
        print("  + domain/clube_tiro/db/dominio_clube_tiro.db")
    if DOCUMENTOS_DIR.exists():
        shutil.copytree(DOCUMENTOS_DIR, destino / "documentos_recebidos")
        print("  + atendimento/documentos_recebidos/")

    _rotacionar()
    print(f"Backup salvo em {destino}")


if __name__ == "__main__":
    main()
