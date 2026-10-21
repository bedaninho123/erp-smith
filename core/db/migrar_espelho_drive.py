"""Tabelas `drive_pasta` e `drive_documento` (2026-10-20): a cópia de
cada documento numa pasta com o nome do cliente no Google Drive -- ver
integracoes/espelho_documentos_drive.py.

Idempotente, e roda sozinha na subida do servidor de produção
(webapp/servir.py), como migrar_codigo_portal.

    .venv\\Scripts\\python.exe -m core.db.migrar_espelho_drive
"""
from core.conexao import conectar_admin


def migrar() -> dict:
    con = conectar_admin()
    try:
        antes = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        con.execute(
            "CREATE TABLE IF NOT EXISTS drive_pasta ("
            "empresa_id TEXT NOT NULL REFERENCES empresa(empresa_id), "
            "chave TEXT NOT NULL, drive_pasta_id TEXT NOT NULL, nome TEXT NOT NULL, "
            "PRIMARY KEY (empresa_id, chave))"
        )
        con.execute(
            "CREATE TABLE IF NOT EXISTS drive_documento ("
            "documento_id TEXT PRIMARY KEY, "
            "empresa_id TEXT NOT NULL REFERENCES empresa(empresa_id), "
            "drive_arquivo_id TEXT NOT NULL, enviado_em TEXT NOT NULL)"
        )
        con.commit()
        return {"tabelas_criadas": sorted({"drive_pasta", "drive_documento"} - antes)}
    finally:
        con.close()


if __name__ == "__main__":
    print(migrar())
