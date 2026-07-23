"""Conexão com o banco do Core. O Core não depende de nenhuma camada
acima dele (Motor IA, Integrações) -- só o contrário."""
import sqlite3

CORE_DB = "core/db/erp_smith.db"


def conectar() -> sqlite3.Connection:
    con = sqlite3.connect(CORE_DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con
