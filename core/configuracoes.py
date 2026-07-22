"""Acesso de leitura à tabela configuracoes do Core."""
import sqlite3

DB_PATH = "core/db/erp_smith.db"


def obter_configuracoes() -> dict:
    con = sqlite3.connect(DB_PATH)
    try:
        return {
            r[0]: r[1]
            for r in con.execute(
                "SELECT chave, valor FROM configuracoes WHERE ativo = 'Sim'"
            )
        }
    finally:
        con.close()
