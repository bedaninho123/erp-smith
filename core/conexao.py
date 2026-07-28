"""Conexão com o banco do Core. O Core não depende de nenhuma camada
acima dele (Motor IA, Integrações) -- só o contrário."""
import os
import sqlite3

# Caminho do banco vem de variável de ambiente com o banco real como
# padrão -- é o que permite a suíte de testes (tests/conftest.py) rodar
# contra um banco descartável sem nunca tocar em core/db/erp_smith.db.
# Lido uma vez na importação: quem quiser trocar precisa definir
# ERP_CORE_DB antes de importar qualquer módulo do Core.
CORE_DB = os.environ.get("ERP_CORE_DB", "core/db/erp_smith.db")


def conectar() -> sqlite3.Connection:
    con = sqlite3.connect(CORE_DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con
