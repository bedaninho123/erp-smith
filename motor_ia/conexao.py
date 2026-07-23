"""Conexão compartilhada com o banco do Core, já com o banco de Domínio
anexado (ATTACH DATABASE) -- usada por qualquer módulo do Motor IA que
precise ler Core e Domínio juntos, na mesma consulta."""
import sqlite3

from core.conexao import CORE_DB

DOMAIN_DB = "domain/clube_tiro/db/dominio_clube_tiro.db"


def conectar() -> sqlite3.Connection:
    con = sqlite3.connect(CORE_DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute(f"ATTACH DATABASE '{DOMAIN_DB}' AS dominio")
    return con
